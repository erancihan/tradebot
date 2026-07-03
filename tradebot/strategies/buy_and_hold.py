"""Always-long: the benchmark every strategy must beat.

Also the natural per-symbol signal when a cross-sectional selector decides
membership — the selector gates which symbols may hold, and buy-and-hold says
"hold whatever I'm allowed to".
"""

from __future__ import annotations

import pandas as pd

from .base import Strategy


class BuyAndHold(Strategy):
    name = "buy_and_hold"

    @property
    def required_history(self) -> int:
        return 1

    def target_positions(self, bars: pd.DataFrame) -> pd.Series:
        self._validate(bars)
        return pd.Series(1, index=bars.index, dtype="int64")
