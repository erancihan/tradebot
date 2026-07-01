"""A tiny registry so strategies can be selected by name from config."""

from __future__ import annotations

from typing import Any

from .base import Strategy
from .rsi_reversion import RsiReversion
from .sma_crossover import SmaCrossover

STRATEGIES: dict[str, type[Strategy]] = {
    SmaCrossover.name: SmaCrossover,
    RsiReversion.name: RsiReversion,
}


def build_strategy(name: str, params: dict[str, Any] | None = None) -> Strategy:
    """Instantiate a strategy by name with keyword params from config."""
    try:
        cls = STRATEGIES[name]
    except KeyError:
        known = ", ".join(sorted(STRATEGIES))
        raise KeyError(f"Unknown strategy {name!r}. Known: {known}") from None
    return cls(**(params or {}))
