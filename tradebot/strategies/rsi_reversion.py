"""RSI mean-reversion: buy oversold, exit when momentum normalises.

Long-only (the default): enter long when RSI drops below `oversold`, and hold
that long until RSI recovers above `exit_level`; otherwise stay flat. Between an
entry and its exit no new instruction is emitted, so the position is carried
forward (forward-filled) — a stateful regime rather than a single-bar flip.

With `allow_short=True` the mirror applies: short above `overbought`, and exit
*either* side inside a symmetric neutral band around 50.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .. import indicators
from .base import Strategy


class RsiReversion(Strategy):
    name = "rsi_reversion"

    def __init__(
        self,
        period: int = 14,
        oversold: float = 30.0,
        overbought: float = 70.0,
        exit_level: float = 50.0,
        allow_short: bool = False,
    ) -> None:
        if not 0 < oversold < exit_level < overbought < 100:
            raise ValueError(
                "Require 0 < oversold < exit_level < overbought < 100, got "
                f"{oversold}, {exit_level}, {overbought}"
            )
        self.period = period
        self.oversold = oversold
        self.overbought = overbought
        self.exit_level = exit_level
        self.allow_short = allow_short

    @property
    def required_history(self) -> int:
        return self.period * 3

    def target_positions(self, bars: pd.DataFrame) -> pd.Series:
        self._validate(bars)
        rsi = indicators.rsi(bars["close"], self.period)

        # NaN means "no instruction this bar"; ffill carries the open position.
        target = pd.Series(np.nan, index=bars.index, dtype="float64")

        if not self.allow_short:
            target[rsi > self.exit_level] = 0.0   # exit long
            target[rsi < self.oversold] = 1.0     # enter long (overrides above)
        else:
            # Exit either side inside a neutral band centred on 50. Width is how
            # far `exit_level` sits from the midpoint (with a sane minimum).
            band = abs(self.exit_level - 50.0) or 5.0
            target[(rsi >= 50.0 - band) & (rsi <= 50.0 + band)] = 0.0
            target[rsi < self.oversold] = 1.0     # enter long
            target[rsi > self.overbought] = -1.0  # enter short

        return target.ffill().fillna(0.0).astype("int64")
