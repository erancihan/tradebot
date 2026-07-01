"""Pluggable trading strategies.

A strategy is a pure function of market data: given a bar DataFrame it returns a
target-position Series in {-1, 0, +1}. It holds no account state and sends no
orders — turning targets into sized orders is the job of the RiskManager and the
engine/backtester. This keeps strategies trivially unit-testable.
"""

from __future__ import annotations

from .base import Strategy
from .bollinger_reversion import BollingerReversion
from .donchian_breakout import DonchianBreakout
from .macd import Macd
from .momentum import Momentum
from .registry import STRATEGIES, build_strategy
from .rsi_reversion import RsiReversion
from .sma_crossover import SmaCrossover
from .supertrend import Supertrend

__all__ = [
    "Strategy",
    "SmaCrossover",
    "RsiReversion",
    "Macd",
    "BollingerReversion",
    "DonchianBreakout",
    "Momentum",
    "Supertrend",
    "STRATEGIES",
    "build_strategy",
]
