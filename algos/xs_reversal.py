"""Example contestant: short-term reversal portfolio (buy the recent losers)."""

from tradebot.allocation import EqualWeight
from tradebot.arena import PortfolioAlgo, register
from tradebot.selection import MomentumSelector
from tradebot.strategies import BuyAndHold


@register(name="xs_reversal", author="house", tags=("portfolio", "mean-reversion"))
class XsReversal(PortfolioAlgo):
    """Hold the 2 biggest 15-bar losers (skip the last bar), equal weight."""

    def __init__(self) -> None:
        super().__init__(
            strategy=BuyAndHold(),
            selector=MomentumSelector(lookback=15, skip=1, top_k=2, reverse=True),
            allocator=EqualWeight(),
        )
