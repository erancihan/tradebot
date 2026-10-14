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

from typing import Any

from .base import Selector
from .ranked import LowVolatilitySelector, MomentumSelector, RankedSelector
from .regime import RegimeSwitchSelector

__all__ = ["SELECTORS", "LowVolatilitySelector", "MomentumSelector", "RankedSelector",
           "RegimeSwitchSelector", "Selector", "build_selector"]

SELECTORS: dict[str, type[Selector]] = {
    MomentumSelector.name: MomentumSelector,
    LowVolatilitySelector.name: LowVolatilitySelector,
    RegimeSwitchSelector.name: RegimeSwitchSelector,
}


def build_selector(name: str, params: dict[str, Any] | None = None) -> Selector:
    """Instantiate a selector by name with keyword params from config."""
    try:
        cls = SELECTORS[name]
    except KeyError:
        known = ", ".join(sorted(SELECTORS))
        raise KeyError(f"Unknown selector {name!r}. Known: {known}") from None
    return cls(**(params or {}))
