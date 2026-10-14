"""Time-series momentum: ride assets that have recently trended, with a filter.

Go long when the ``lookback``-bar rate-of-change exceeds ``threshold`` percent
(and, if ``trend_ma`` is set, price is above that SMA); go short on the mirror
when ``allow_short`` is on; otherwise flat. Stateless per-bar rule — the momentum
sign sets the regime each bar, and NaN during warm-up defaults to flat.

The optional ``trend_ma`` filter suppresses counter-trend entries: a positive ROC
alone can fire inside a broader downtrend, so requiring price above a long SMA (and
below it for shorts) keeps the position aligned with the dominant trend.
"""

from __future__ import annotations

import pandas as pd

from .. import indicators
from .base import Strategy


class Momentum(Strategy):
    name = "momentum"

    def __init__(
        self,
        lookback: int = 90,
        threshold: float = 0.0,
        trend_ma: int = 0,
        allow_short: bool = False,
    ) -> None:
        if lookback < 1:
            raise ValueError(f"lookback ({lookback}) must be >= 1")
        if threshold < 0:
            raise ValueError(f"threshold ({threshold}) is a magnitude and must be >= 0")
        if trend_ma < 0:
            raise ValueError(f"trend_ma ({trend_ma}) must be >= 0 (0 disables)")
        self.lookback = lookback
        self.threshold = threshold
        self.trend_ma = trend_ma
        self.allow_short = allow_short

    @property
    def required_history(self) -> int:
        return max(self.lookback, self.trend_ma) + 5

    def target_positions(self, bars: pd.DataFrame) -> pd.Series:
        self._validate(bars)
        close = bars["close"]
        change = indicators.roc(close, self.lookback)

        long_ok = change > self.threshold
        short_ok = change < -self.threshold
        if self.trend_ma > 0:
            ma = indicators.sma(close, self.trend_ma)
            long_ok = long_ok & (close > ma)
            short_ok = short_ok & (close < ma)

        target = pd.Series(0, index=bars.index, dtype="int64")
        target[long_ok.fillna(False)] = 1
        if self.allow_short:
            target[short_ok.fillna(False)] = -1
        return target
