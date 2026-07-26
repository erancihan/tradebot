"""Canary: select on FUTURE returns. Deliberately cheats.

⚠ THIS CONTESTANT USES LOOK-AHEAD ON PURPOSE. It is not a trading idea, it is
not promotable, it must never be a baseline, and it must never enter a season.
It exists to answer one question about a *scenario*: is there anything in here
to find?

If an algorithm that can see the future cannot beat the field by a wide margin,
the scenario contains no exploitable cross-sectional signal, and every verdict
produced on it — pass or fail — is noise. That makes the oracle the upper bound
of the bracket and the sharpest single test of whether a scenario is worth
running at all.

Expected position in the bracket: **first, by a wide margin**.
"""

from __future__ import annotations

import pandas as pd

from tradebot.allocation import EqualWeight
from tradebot.arena import PortfolioAlgo, register
from tradebot.selection import RankedSelector, Selector
from tradebot.strategies import BuyAndHold


class OracleSelector(Selector):
    """Hold the K names with the best return over the NEXT ``horizon`` bars.

    Violates prefix-stability by design — that is the whole point, and it is
    why this class lives under `algos/canaries/` rather than in
    `tradebot.selection`. The execution loops shift membership by one bar, so
    the oracle still cannot trade the bar it forms its verdict on; it simply
    knows which names are about to do well.
    """

    name = "oracle_topk"

    def __init__(self, top_k: int = 2, horizon: int = 20) -> None:
        self.top_k = top_k
        self.horizon = horizon
        self.required_history = 2

    def membership(self, frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
        closes = RankedSelector._closes(frames)
        if closes.empty:
            return pd.DataFrame(columns=list(frames))
        # Forward return over the next `horizon` bars — future information.
        future = closes.shift(-self.horizon) / closes - 1.0
        k = min(self.top_k, len(closes.columns))
        ranks = future.rank(axis=1, ascending=False, method="first")
        member = ranks <= k
        # The tail has no future left to see; fall back to holding everything so
        # the contestant does not silently go flat at the end of the sample.
        member.iloc[-self.horizon:] = True
        return member.fillna(False)


@register(name="oracle_topk", author="canary",
          tags=("canary", "diagnostic", "look-ahead"), family="canary")
class OracleTopK(PortfolioAlgo):
    """Cheats with future returns. Must win by a wide margin — or the scenario
    has no signal in it. NEVER promotable."""

    def __init__(self) -> None:
        super().__init__(
            strategy=BuyAndHold(),
            selector=OracleSelector(top_k=2, horizon=20),
            allocator=EqualWeight(),
        )
