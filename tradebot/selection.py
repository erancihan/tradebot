"""Cross-sectional selection: decide *which* symbols may be held.

A :class:`Selector` looks at the whole candidate pool at once — something a
per-symbol ``Strategy`` deliberately cannot do — and produces a membership
verdict per symbol per bar. Membership *gates* the strategy signal (a symbol
outside the selection is forced flat); it never sizes anything, so the layering
stays strategy → selector gate → allocator weights → RiskManager quantities.

Selection must be prefix-stable (no look-ahead): the verdict at bar ``t`` may
depend only on bars ``≤ t`` and on earlier verdicts, so recomputing over any
prefix of history reproduces that prefix exactly. That property is what lets
the live engine simply recompute from full fetched history every pass (bars
are the source of truth — same pattern as the arena season) and what the
backtester's one-bar shift relies on.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import numpy as np
import pandas as pd


class Selector(ABC):
    """Base class for cross-sectional selectors."""

    #: Name used in config (`portfolio.selector.name`) and logs.
    name: str = "selector"

    #: Bars needed before the selector can produce a verdict.
    required_history: int = 1

    @abstractmethod
    def membership(self, frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
        """Boolean membership matrix (index = bars, columns = symbols).

        ``True`` at ``(t, s)`` means the selector wants ``s`` holdable based on
        data ``≤ t``. Must be prefix-stable.
        """

    def latest_targets(self, frames: dict[str, pd.DataFrame]) -> dict[str, int]:
        """Convenience for live trading: the most recent verdict per symbol."""
        member = self.membership(frames)
        if member.empty:
            return {s: 0 for s in frames}
        last = member.iloc[-1]
        return {s: int(bool(last.get(s, False))) for s in frames}


class MomentumSelector(Selector):
    """Classic cross-sectional momentum: hold the top-K trailing performers.

    Each bar, candidates are scored by their ``lookback``-bar return *skipping*
    the most recent ``skip`` bars (the standard "12-1" construction — recent
    bars are excluded to dodge short-term reversal). The best ``top_k`` are
    held, with hysteresis to control turnover: a current holding is only
    dropped once its rank slips below ``exit_rank`` (default 1.5×K), so names
    hovering at the boundary don't churn in and out every bar.

    Symbols without a full ``lookback`` of history are unmeasurable and never
    selected — don't hold what you can't rank.
    """

    name = "momentum"

    def __init__(
        self,
        lookback: int = 252,
        skip: int = 21,
        top_k: int = 5,
        exit_rank: int | None = None,
    ) -> None:
        if lookback <= skip:
            raise ValueError(f"lookback ({lookback}) must exceed skip ({skip})")
        if skip < 0:
            raise ValueError(f"skip must be >= 0, got {skip}")
        if top_k < 1:
            raise ValueError(f"top_k must be >= 1, got {top_k}")
        if exit_rank is None:
            exit_rank = top_k + max(top_k // 2, 1)
        if exit_rank < top_k:
            raise ValueError(f"exit_rank ({exit_rank}) must be >= top_k ({top_k})")
        self.lookback = lookback
        self.skip = skip
        self.top_k = top_k
        self.exit_rank = exit_rank
        self.required_history = lookback + 1

    def scores(self, frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
        """Momentum score matrix: return from bar ``t-lookback`` to ``t-skip``."""
        closes = pd.DataFrame({s: f["close"] for s, f in frames.items()}).sort_index()
        return closes.shift(self.skip) / closes.shift(self.lookback) - 1.0

    def membership(self, frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
        scores = self.scores(frames)
        held: set[str] = set()
        rows: list[dict[str, bool]] = []
        for _, row in scores.iterrows():
            ranked = self._rank(row)
            rank_of = {s: r + 1 for r, s in enumerate(ranked)}
            keep = {s for s in held if rank_of.get(s, np.inf) <= self.exit_rank}
            for s in ranked:
                if len(keep) >= self.top_k:
                    break
                keep.add(s)
            held = keep
            rows.append({s: s in keep for s in scores.columns})
        return pd.DataFrame(rows, index=scores.index, columns=scores.columns)

    @staticmethod
    def _rank(row: pd.Series) -> list[str]:
        """Symbols by descending score; ties broken alphabetically (determinism)."""
        valid = row.dropna()
        return sorted(valid.index, key=lambda s: (-valid[s], s))


SELECTORS: dict[str, type[Selector]] = {
    MomentumSelector.name: MomentumSelector,
}


def build_selector(name: str, params: dict[str, Any] | None = None) -> Selector:
    """Instantiate a selector by name with keyword params from config."""
    try:
        cls = SELECTORS[name]
    except KeyError:
        known = ", ".join(sorted(SELECTORS))
        raise KeyError(f"Unknown selector {name!r}. Known: {known}") from None
    return cls(**(params or {}))
