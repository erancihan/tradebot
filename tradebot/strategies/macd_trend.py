"""MACD trend-following: long while the MACD line is above its signal line.

The MACD line (fast EMA minus slow EMA) measures trend direction and strength;
its own EMA (the signal line) lags it, so the spread flips sign near trend
turns. Flat (or short, if enabled) while the line is below the signal.
"""

from __future__ import annotations

import pandas as pd

from .. import indicators
from .base import Strategy


class MacdTrend(Strategy):
    name = "macd_trend"

    def __init__(
        self,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
        allow_short: bool = False,
    ) -> None:
        if not 0 < fast < slow:
            raise ValueError(f"require 0 < fast < slow, got {fast}, {slow}")
        if signal < 1:
            raise ValueError("signal must be >= 1")
        self.fast = fast
        self.slow = slow
        self.signal = signal
        self.allow_short = allow_short

    @property
    def required_history(self) -> int:
        # The signal line is an EMA of an EMA-difference: both need warmup.
        return self.slow + self.signal + 10

    def target_positions(self, bars: pd.DataFrame) -> pd.Series:
        self._validate(bars)
        macd_line, signal_line, _ = indicators.macd(
            bars["close"], self.fast, self.slow, self.signal
        )
        target = pd.Series(0, index=bars.index, dtype="int64")
        target[macd_line > signal_line] = 1
        if self.allow_short:
            target[macd_line < signal_line] = -1
        # NaN comparisons are False during warmup -> flat, the safe default.
        return target
