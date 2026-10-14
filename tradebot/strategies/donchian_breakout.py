"""Donchian channel breakout: the classic turtle-style trend entry.

Go long when the close breaks above the prior `entry`-bar high; exit when it
breaks below the prior `exit`-bar low (a tighter trailing channel). Between
those signals the position is carried forward. With `allow_short=True` the
mirror applies on the downside.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .base import Strategy


class DonchianBreakout(Strategy):
    name = "donchian_breakout"

    def __init__(self, entry: int = 20, exit: int = 10, allow_short: bool = False) -> None:
        if not 1 <= exit < entry:
            raise ValueError(f"require 1 <= exit < entry, got exit={exit}, entry={entry}")
        self.entry = entry
        self.exit = exit
        self.allow_short = allow_short

    @property
    def required_history(self) -> int:
        return self.entry + 5

    def target_positions(self, bars: pd.DataFrame) -> pd.Series:
        self._validate(bars)
        close = bars["close"]
        # Channels are built from *prior* bars only (shift(1)), so today's
        # close can break out of yesterday's channel without self-reference.
        entry_high = close.rolling(self.entry, min_periods=self.entry).max().shift(1)
        exit_low = close.rolling(self.exit, min_periods=self.exit).min().shift(1)

        # NaN = "no instruction"; ffill carries the open position (see
        # rsi_reversion for the pattern). Exits first, entries override —
        # a breakout bar that also crosses the opposite exit still enters.
        target = pd.Series(np.nan, index=bars.index, dtype="float64")
        target[close < exit_low] = 0.0
        if self.allow_short:
            entry_low = close.rolling(self.entry, min_periods=self.entry).min().shift(1)
            exit_high = close.rolling(self.exit, min_periods=self.exit).max().shift(1)
            target[close > exit_high] = 0.0
            target[close < entry_low] = -1.0
        target[close > entry_high] = 1.0
        return target.ffill().fillna(0.0).astype("int64")
