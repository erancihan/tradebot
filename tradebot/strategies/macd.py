"""MACD crossover: a momentum/trend strategy.

Go long when the MACD line leads its signal line (or, with ``use_hist``, when the
MACD histogram is positive); go flat — or short, if enabled — otherwise. This is a
stateless per-bar rule like ``SmaCrossover``: the sign of the momentum spread sets
the regime each bar, so during the EMA warm-up (NaN) comparisons are False and the
target stays flat.
"""

from __future__ import annotations

import pandas as pd

from .. import indicators
from .base import Strategy


class Macd(Strategy):
    name = "macd"

    def __init__(
        self,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
        use_hist: bool = False,
        allow_short: bool = False,
    ) -> None:
        if min(fast, slow, signal) < 1:
            raise ValueError("fast, slow and signal must all be >= 1")
        if fast >= slow:
            raise ValueError(f"fast ({fast}) must be < slow ({slow})")
        self.fast = fast
        self.slow = slow
        self.signal = signal
        self.use_hist = use_hist
        self.allow_short = allow_short

    @property
    def required_history(self) -> int:
        # Slow EMA plus the signal EMA on top of it, with headroom.
        return self.slow + self.signal + 5

    def target_positions(self, bars: pd.DataFrame) -> pd.Series:
        self._validate(bars)
        m = indicators.macd(bars["close"], self.fast, self.slow, self.signal)
        if self.use_hist:
            bull, bear = m["hist"] > 0, m["hist"] < 0
        else:
            bull, bear = m["macd"] > m["signal"], m["macd"] < m["signal"]

        target = pd.Series(0, index=bars.index, dtype="int64")
        target[bull] = 1
        if self.allow_short:
            target[bear] = -1
        return target
