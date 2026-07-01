"""Moving-average crossover: a classic trend-following strategy.

Go long when the fast MA is above the slow MA; go flat (or short, if enabled)
when it is below. Works with either simple or exponential moving averages.
"""

from __future__ import annotations

import pandas as pd

from .. import indicators
from .base import Strategy


class SmaCrossover(Strategy):
    name = "sma_crossover"

    def __init__(
        self,
        fast: int = 20,
        slow: int = 50,
        use_ema: bool = False,
        allow_short: bool = False,
    ) -> None:
        if fast >= slow:
            raise ValueError(f"fast ({fast}) must be < slow ({slow})")
        self.fast = fast
        self.slow = slow
        self.use_ema = use_ema
        self.allow_short = allow_short

    @property
    def required_history(self) -> int:
        # A little headroom beyond `slow` so the average is well-formed.
        return self.slow + 5

    def target_positions(self, bars: pd.DataFrame) -> pd.Series:
        self._validate(bars)
        close = bars["close"]
        ma = indicators.ema if self.use_ema else indicators.sma
        fast_ma = ma(close, self.fast)
        slow_ma = ma(close, self.slow)

        target = pd.Series(0, index=bars.index, dtype="int64")
        target[fast_ma > slow_ma] = 1
        if self.allow_short:
            target[fast_ma < slow_ma] = -1
        # While the slow MA is still warming up both MAs are NaN -> comparisons
        # are False -> target stays 0 (flat), which is the safe default.
        return target
