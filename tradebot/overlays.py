"""Portfolio overlays: risk transforms applied to proposed weights.

An :class:`Overlay` sits between the allocator and the RiskManager: it receives
the proposed weights (plus targets and decision-time history) and returns
adjusted weights. Overlays are **reduce-only by convention** — they scale
exposure *down* (vol regimes, sector concentration) and never add or lever up —
so stacking them can only make the book safer. The RiskManager's per-name and
gross caps still apply afterwards; overlays are an extra dial, not a bypass.

Overlays run in the order configured (`portfolio.overlays`), and each sees the
previous one's output. Recommended order: structural caps first (sector), the
volatility dial last (it should measure the book it will actually scale).

Like allocators, overlays are look-ahead safe: callers pass only bars available
at decision time. When an overlay cannot measure what it needs (short history),
it leaves the weights unchanged — absence of evidence never *adds* risk here,
because the un-scaled weights were already deemed acceptable by the risk caps.
"""

from __future__ import annotations

import csv
import math
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import pandas as pd


class Overlay(ABC):
    """Base class for weight-transforming portfolio overlays."""

    #: Name used in config (`portfolio.overlays[].name`) and logs.
    name: str = "overlay"

    #: Bars needed before the overlay can act (used for warmup sizing).
    required_history: int = 1

    @abstractmethod
    def transform(
        self,
        weights: dict[str, float],
        targets: dict[str, int],
        history: dict[str, pd.DataFrame],
    ) -> dict[str, float]:
        """Return adjusted weights (never larger than the inputs)."""


class VolTargetOverlay(Overlay):
    """Volatility-targeting exposure dial: de-risk when the book runs hot.

    Realized volatility of the *proposed* book (the weight-summed member
    returns over the trailing ``window`` bars, annualized) is compared with
    ``target_vol``; when it exceeds the target, every weight is scaled by
    ``target_vol / realized`` — capped at 1.0, so calm regimes are never
    levered up. If the book's recent returns can't be measured (short or gappy
    history), weights pass through unchanged.
    """

    name = "vol_target"

    def __init__(
        self,
        target_vol: float = 0.15,
        window: int = 20,
        annualization: float = 252.0,
    ) -> None:
        if target_vol <= 0:
            raise ValueError(f"target_vol must be > 0, got {target_vol}")
        if window < 2:
            raise ValueError(f"window must be >= 2, got {window}")
        if annualization <= 0:
            raise ValueError(f"annualization must be > 0, got {annualization}")
        self.target_vol = target_vol
        self.window = window
        self.annualization = annualization
        self.required_history = window + 1

    def transform(
        self,
        weights: dict[str, float],
        targets: dict[str, int],
        history: dict[str, pd.DataFrame],
    ) -> dict[str, float]:
        funded = {s: w for s, w in weights.items() if w > 0 and s in history}
        if not funded:
            return dict(weights)
        closes = pd.DataFrame({s: history[s]["close"] for s in funded})
        returns = closes.pct_change().dropna()
        if len(returns) < self.window:
            return dict(weights)
        recent = returns.iloc[-self.window:]
        # Book return: weighted member returns; the un-invested rest is cash.
        book = (recent * pd.Series(funded)).sum(axis=1)
        realized = float(book.std()) * math.sqrt(self.annualization)
        if not math.isfinite(realized) or realized <= 0:
            return dict(weights)
        scale = min(1.0, self.target_vol / realized)
        return {s: w * scale for s, w in weights.items()}


class SectorCapOverlay(Overlay):
    """Cap the total weight per sector so a screen can't become one factor bet.

    Symbols map to sectors via the ``sectors`` dict and/or a ``sectors_file``
    CSV (``symbol,sector`` rows, optional header). Any symbol *not* in the map
    lands in ``default_sector`` — one shared capped bucket, so unknown names
    are conservatively treated as correlated rather than silently uncapped.
    Sectors over ``max_sector_pct`` are scaled down proportionally; the excess
    stays in cash (never redistributed into other sectors).
    """

    name = "sector_cap"

    def __init__(
        self,
        max_sector_pct: float = 0.5,
        sectors: dict[str, str] | None = None,
        sectors_file: str | None = None,
        default_sector: str = "other",
    ) -> None:
        if not 0 < max_sector_pct <= 1:
            raise ValueError(f"max_sector_pct must be in (0, 1], got {max_sector_pct}")
        mapping = {str(k).upper(): str(v) for k, v in (sectors or {}).items()}
        if sectors_file:
            mapping.update(self._load_csv(sectors_file))
        if not mapping:
            raise ValueError(
                "sector_cap needs a symbol->sector mapping "
                "(`sectors` and/or `sectors_file`)"
            )
        self.max_sector_pct = max_sector_pct
        self.sectors = mapping
        self.default_sector = default_sector

    @staticmethod
    def _load_csv(path: str) -> dict[str, str]:
        mapping: dict[str, str] = {}
        with Path(path).open(newline="") as fh:
            for row in csv.reader(fh):
                if len(row) < 2:
                    continue
                sym, sector = row[0].strip(), row[1].strip()
                if not sym or sym.lower() == "symbol":   # skip blank/header rows
                    continue
                mapping[sym.upper()] = sector
        return mapping

    def transform(
        self,
        weights: dict[str, float],
        targets: dict[str, int],
        history: dict[str, pd.DataFrame],
    ) -> dict[str, float]:
        by_sector: dict[str, list[str]] = {}
        for sym, w in weights.items():
            if w <= 0:
                continue
            sector = self.sectors.get(sym.upper(), self.default_sector)
            by_sector.setdefault(sector, []).append(sym)

        out = dict(weights)
        for syms in by_sector.values():
            total = sum(out[s] for s in syms)
            if total > self.max_sector_pct:
                scale = self.max_sector_pct / total
                for s in syms:
                    out[s] *= scale
        return out


OVERLAYS: dict[str, type[Overlay]] = {
    VolTargetOverlay.name: VolTargetOverlay,
    SectorCapOverlay.name: SectorCapOverlay,
}


def build_overlay(name: str, params: dict[str, Any] | None = None) -> Overlay:
    """Instantiate an overlay by name with keyword params from config."""
    try:
        cls = OVERLAYS[name]
    except KeyError:
        known = ", ".join(sorted(OVERLAYS))
        raise KeyError(f"Unknown overlay {name!r}. Known: {known}") from None
    return cls(**(params or {}))


def apply_overlays(
    overlays: list[Overlay],
    weights: dict[str, float],
    targets: dict[str, int],
    history: dict[str, pd.DataFrame],
) -> dict[str, float]:
    """Run the overlay chain in order; each sees the previous one's output."""
    for overlay in overlays:
        weights = overlay.transform(weights, targets, history)
    return weights
