"""Donchian channel breakout: a classic trend-following (turtle) strategy.

Long-only (default): go long when the close breaks above the highest high of the
prior ``entry_window`` bars; exit to flat when it breaks below the lowest low of
the prior (shorter) ``exit_window`` bars. This is a *stateful regime*: between the
entry breakout and the exit breakdown no new instruction is emitted, so the long
is forward-filled.

With ``allow_short=True`` it becomes an always-in reversal system on the entry
channel: long on an upper breakout, short on a lower breakout, flip on the
opposite breakout (``exit_window`` then only governs the long-only flat exit).

No look-ahead: channels are ``shift(1)``-ed so the current bar is compared against
the *prior* window, never a window that includes itself.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .. import indicators
from .base import Strategy


class DonchianBreakout(Strategy):
    name = "donchian_breakout"

    def __init__(
        self,
        entry_window: int = 20,
        exit_window: int = 10,
        allow_short: bool = False,
    ) -> None:
        if entry_window < 2:
            raise ValueError(f"entry_window ({entry_window}) must be >= 2")
        if exit_window < 2:
            raise ValueError(f"exit_window ({exit_window}) must be >= 2")
        if exit_window > entry_window:
            raise ValueError(
                f"exit_window ({exit_window}) must be <= entry_window ({entry_window})"
            )
        self.entry_window = entry_window
        self.exit_window = exit_window
        self.allow_short = allow_short

    @property
    def required_history(self) -> int:
        return self.entry_window + 5

    def target_positions(self, bars: pd.DataFrame) -> pd.Series:
        self._validate(bars)
        high, low, close = bars["high"], bars["low"], bars["close"]
        entry = indicators.donchian(high, low, self.entry_window)
        # Prior-window channels: shift(1) so a break is measured against history.
        entry_up = entry["upper"].shift(1)
        entry_lo = entry["lower"].shift(1)

        target = pd.Series(np.nan, index=bars.index, dtype="float64")

        if not self.allow_short:
            exit_ch = indicators.donchian(high, low, self.exit_window)
            exit_lo = exit_ch["lower"].shift(1)
            target[close < exit_lo] = 0.0       # breakdown -> exit long
            target[close > entry_up] = 1.0      # breakout -> enter long
        else:
            # Always-in reversal: flip on the opposite entry-channel breakout.
            target[close > entry_up] = 1.0
            target[close < entry_lo] = -1.0

        return target.ffill().fillna(0.0).astype("int64")
