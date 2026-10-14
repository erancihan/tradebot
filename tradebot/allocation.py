"""Portfolio allocation: turn a set of targets into per-symbol weights.

An :class:`Allocator` answers one question per rebalance: *given which symbols
the strategy wants held (targets in {-1, 0, +1}) and the bar history available
at decision time, what fraction of equity should each get?* Weights are
unsigned budgets — direction still comes from the target sign — and they are
advisory: the RiskManager caps each at ``max_position_pct`` and scales the book
to ``max_gross_exposure`` before any quantity is computed, so allocators can't
bypass risk limits.

Allocators must be look-ahead safe: callers pass only bars available at
decision time, and implementations may not mutate or peek beyond them. Without
an allocator, every symbol gets the legacy fixed ``max_position_pct`` slug.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import pandas as pd

from .indicators import rolling_volatility


class Allocator(ABC):
    """Base class for allocation schemes.

    ``weights`` receives every symbol under consideration (its target may be
    0) and returns a weight only for the symbols it wants funded; missing
    symbols are treated as 0 by the RiskManager.
    """

    #: Name used in config (`portfolio.allocation`) and logs.
    name: str = "allocator"

    #: Bars needed before the allocator can weight (used for warmup sizing).
    required_history: int = 1

    @abstractmethod
    def weights(
        self, targets: dict[str, int], history: dict[str, pd.DataFrame]
    ) -> dict[str, float]:
        """Return unsigned equity fractions for the active (non-flat) symbols.

        ``history`` maps each symbol to the bars available at decision time —
        never including the bar the resulting orders will fill on.
        """

    @staticmethod
    def _active(targets: dict[str, int]) -> list[str]:
        return [s for s, t in targets.items() if t != 0]


class EqualWeight(Allocator):
    """1/N over the active symbols — the classic hard-to-beat baseline.

    ``gross_target`` is the total fraction of equity to deploy across the
    book (before risk caps); each active symbol gets an equal share of it.
    """

    name = "equal"

    def __init__(self, gross_target: float = 1.0) -> None:
        if not 0 < gross_target <= 1:
            raise ValueError(f"gross_target must be in (0, 1], got {gross_target}")
        self.gross_target = gross_target

    def weights(
        self, targets: dict[str, int], history: dict[str, pd.DataFrame]
    ) -> dict[str, float]:
        active = self._active(targets)
        if not active:
            return {}
        share = self.gross_target / len(active)
        return {s: share for s in active}


class InverseVolatility(Allocator):
    """Weight active symbols by 1/volatility, so risk (not dollars) is spread.

    Volatility is the rolling stdev of daily returns over ``window`` bars of
    the provided history. Symbols without a full window (or with zero measured
    volatility) get no allocation — we don't fund what we can't measure — so
    pick a ``window`` no larger than the strategy warmup if trading should
    start with the first signal.
    """

    name = "inverse_vol"

    def __init__(self, window: int = 63, gross_target: float = 1.0) -> None:
        if window < 2:
            raise ValueError(f"window must be >= 2, got {window}")
        if not 0 < gross_target <= 1:
            raise ValueError(f"gross_target must be in (0, 1], got {gross_target}")
        self.window = window
        self.gross_target = gross_target
        self.required_history = window + 1

    def weights(
        self, targets: dict[str, int], history: dict[str, pd.DataFrame]
    ) -> dict[str, float]:
        inverse: dict[str, float] = {}
        for s in self._active(targets):
            bars = history.get(s)
            if bars is None or len(bars) < 2:
                continue
            vol = rolling_volatility(bars["close"], self.window).iloc[-1]
            if pd.notna(vol) and vol > 0:
                inverse[s] = 1.0 / float(vol)
        total = sum(inverse.values())
        if total <= 0:
            return {}
        return {s: self.gross_target * inv / total for s, inv in inverse.items()}


class ExplicitWeights(Allocator):
    """Owner-specified fixed weights per symbol (fractions of equity).

    Symbols absent from the mapping get nothing, and the weights are used
    as-is (not normalised), so a sum below 1.0 deliberately keeps cash aside.
    """

    name = "explicit"

    def __init__(self, weights: dict[str, float]) -> None:
        if not weights:
            raise ValueError("explicit allocation requires a non-empty weights mapping")
        for sym, w in weights.items():
            if not 0 <= float(w) <= 1:
                raise ValueError(f"weight for {sym} must be in [0, 1], got {w}")
        self._weights = {sym: float(w) for sym, w in weights.items()}

    def weights(
        self, targets: dict[str, int], history: dict[str, pd.DataFrame]
    ) -> dict[str, float]:
        return {s: self._weights.get(s, 0.0) for s in self._active(targets)}


ALLOCATORS: dict[str, type[Allocator]] = {
    EqualWeight.name: EqualWeight,
    InverseVolatility.name: InverseVolatility,
    ExplicitWeights.name: ExplicitWeights,
}


def build_allocator(name: str, params: dict[str, Any] | None = None) -> Allocator:
    """Instantiate an allocator by name with keyword params from config."""
    try:
        cls = ALLOCATORS[name]
    except KeyError:
        known = ", ".join(sorted(ALLOCATORS))
        raise KeyError(f"Unknown allocation scheme {name!r}. Known: {known}") from None
    return cls(**(params or {}))
