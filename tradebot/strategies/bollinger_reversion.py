"""Bollinger-band mean reversion: buy the dip below the band, exit at the mean.

Enter long when the close drops below the lower band (an outsized down-move
relative to recent volatility) and hold until the close reverts to the middle
band. With `allow_short=True` the mirror applies above the upper band. Exits
depend on which side the position is on, so the position is derived with a
causal walk (bar `t`'s verdict uses only bars ``<= t``) rather than ffill.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .. import indicators
from .base import Strategy


class BollingerReversion(Strategy):
    name = "bollinger_reversion"

    def __init__(self, window: int = 20, num_std: float = 2.0, allow_short: bool = False) -> None:
        if window < 2:
            raise ValueError("window must be >= 2")
        if num_std <= 0:
            raise ValueError("num_std must be > 0")
        self.window = window
        self.num_std = num_std
        self.allow_short = allow_short

    @property
    def required_history(self) -> int:
        return self.window * 2

    def target_positions(self, bars: pd.DataFrame) -> pd.Series:
        self._validate(bars)
        close = bars["close"].to_numpy()
        middle, upper, lower = indicators.bollinger_bands(
            bars["close"], self.window, self.num_std
        )
        mid = middle.to_numpy()
        up = upper.to_numpy()
        lo = lower.to_numpy()

        out = np.zeros(len(close), dtype="int64")
        pos = 0
        for i in range(len(close)):
            if np.isnan(mid[i]):
                pos = 0            # bands not warm yet -> stay flat
            else:
                # Exit at the mean first; an extreme bar may exit and flip.
                if pos == 1 and close[i] >= mid[i]:
                    pos = 0
                elif pos == -1 and close[i] <= mid[i]:
                    pos = 0
                if pos == 0:
                    if close[i] < lo[i]:
                        pos = 1
                    elif self.allow_short and close[i] > up[i]:
                        pos = -1
            out[i] = pos
        return pd.Series(out, index=bars.index, dtype="int64")
