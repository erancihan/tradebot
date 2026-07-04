"""Example contestant: a whole momentum portfolio competing as one entry.

Selector-only book: BuyAndHold makes membership the sole signal, so this is
the classic "hold the top-2 trailing performers" portfolio, weighted by
inverse volatility.
"""

from tradebot.allocation import InverseVolatility
from tradebot.arena import PortfolioAlgo, register
from tradebot.selection import MomentumSelector
from tradebot.strategies import BuyAndHold


@register(name="xs_momentum", author="house", tags=("portfolio", "momentum"))
class XsMomentum(PortfolioAlgo):
    """Hold the top-2 by 60-bar momentum (skip 5), inverse-vol weighted."""

    def __init__(self) -> None:
        super().__init__(
            strategy=BuyAndHold(),
            selector=MomentumSelector(lookback=60, skip=5, top_k=2),
            allocator=InverseVolatility(window=30),
        )
