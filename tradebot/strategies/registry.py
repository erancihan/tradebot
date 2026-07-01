"""A tiny registry so strategies can be selected by name from config."""

from __future__ import annotations

from typing import Any

from .base import Strategy
from .bollinger_reversion import BollingerReversion
from .donchian_breakout import DonchianBreakout
from .macd import Macd
from .momentum import Momentum
from .rsi_reversion import RsiReversion
from .sma_crossover import SmaCrossover
from .supertrend import Supertrend

STRATEGIES: dict[str, type[Strategy]] = {
    SmaCrossover.name: SmaCrossover,
    RsiReversion.name: RsiReversion,
    Macd.name: Macd,
    BollingerReversion.name: BollingerReversion,
    DonchianBreakout.name: DonchianBreakout,
    Momentum.name: Momentum,
    Supertrend.name: Supertrend,
}


def build_strategy(name: str, params: dict[str, Any] | None = None) -> Strategy:
    """Instantiate a strategy by name with keyword params from config."""
    try:
        cls = STRATEGIES[name]
    except KeyError:
        known = ", ".join(sorted(STRATEGIES))
        raise KeyError(f"Unknown strategy {name!r}. Known: {known}") from None
    return cls(**(params or {}))
