"""Canary: hold the defensive name and nothing else.

Not a trading idea. This exists to answer one question about a *scenario*: is
hiding free? If a book that never times anything and simply sits in the haven
can win, then the scenario rewards defence for existing rather than for being
deployed at the right moment — and a defensive candidate would score well there
without demonstrating any skill.

Expected position in the bracket: **last, everywhere**. See the README.
"""

from __future__ import annotations

import pandas as pd

from tradebot.allocation import EqualWeight
from tradebot.arena import PortfolioAlgo, register
from tradebot.selection import RankedSelector, Selector
from tradebot.strategies import BuyAndHold


class AlwaysHavenSelector(Selector):
    """Hold ``HAVEN`` if the pool has one, else the single lowest-volatility name.

    The fallback keeps the canary meaningful on pools that do not use the
    factor library's naming, where "the defensive name" still has an answer.
    """

    name = "always_haven"
    required_history = 2

    def membership(self, frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
        closes = RankedSelector._closes(frames)
        if closes.empty:
            return pd.DataFrame(columns=list(frames))
        if "HAVEN" in closes.columns:
            pick = "HAVEN"
        else:
            # Lowest realized volatility over the whole sample. Using the full
            # sample is look-ahead in principle, but this contestant is a
            # diagnostic and is never promotable; the choice is constant across
            # bars so it cannot fabricate timing skill.
            pick = closes.pct_change().std().idxmin()
        out = pd.DataFrame(False, index=closes.index, columns=closes.columns)
        out[pick] = True
        return out


@register(name="always_haven", author="canary", tags=("canary", "diagnostic"),
          family="canary")
class AlwaysHaven(PortfolioAlgo):
    """Sits in the haven forever. Must lose everywhere."""

    def __init__(self) -> None:
        super().__init__(
            strategy=BuyAndHold(),
            selector=AlwaysHavenSelector(),
            allocator=EqualWeight(),
        )
