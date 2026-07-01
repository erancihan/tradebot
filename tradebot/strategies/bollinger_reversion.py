"""Bollinger-band mean reversion: fade stretched moves back to the mean.

Long-only (default): enter long when the close pierces the lower band, and hold
until it reverts up through the middle band (SMA), then go flat. Like
``RsiReversion`` this is a *stateful regime* — between entry and exit no new
instruction is emitted (NaN), so the position is forward-filled.

With ``allow_short=True`` the mirror applies: short above the upper band, and exit
either side when price crosses back through the middle band.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .. import indicators
from .base import Strategy


class BollingerReversion(Strategy):
    name = "bollinger_reversion"

    def __init__(
        self,
        window: int = 20,
        num_std: float = 2.0,
        allow_short: bool = False,
    ) -> None:
        if window < 2:
            raise ValueError(f"window ({window}) must be >= 2")
        if num_std <= 0:
            raise ValueError(f"num_std ({num_std}) must be > 0")
        self.window = window
        self.num_std = num_std
        self.allow_short = allow_short

    @property
    def required_history(self) -> int:
        return self.window + 5

    def target_positions(self, bars: pd.DataFrame) -> pd.Series:
        self._validate(bars)
        close = bars["close"]
        band = indicators.bollinger(close, self.window, self.num_std)
        mid, upper, lower = band["mid"], band["upper"], band["lower"]

        # NaN means "no instruction this bar"; ffill carries the open position.
        target = pd.Series(np.nan, index=bars.index, dtype="float64")

        if not self.allow_short:
            # Exit long when price reverts up through the mean; enter when it
            # pierces the lower band (entry set last so it wins on the same bar).
            target[indicators.crossover(close, mid)] = 0.0
            target[close < lower] = 1.0
        else:
            # Exit either side on a mean crossing; then (re)enter at the bands.
            target[indicators.crossover(close, mid) | indicators.crossunder(close, mid)] = 0.0
            target[close < lower] = 1.0
            target[close > upper] = -1.0

        return target.ffill().fillna(0.0).astype("int64")
