"""Example contestants: a momentum portfolio competing as one entry.

Selector-only books: BuyAndHold makes membership the sole signal, so this is
the classic "hold the top-2 trailing performers" portfolio, weighted by
inverse volatility. Two variants share the ``xs_momentum`` family (the
journal counts their attempts together): the raw book, and the same book
behind a vol-target dial — the pass gate showed raw momentum wins on average
but takes a momentum-crash drawdown, which the overlay exists to cap.
"""

from tradebot.allocation import InverseVolatility
from tradebot.arena import PortfolioAlgo, register
from tradebot.overlays import VolTargetOverlay
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


@register(name="xs_momentum_vt", author="house",
          tags=("portfolio", "momentum", "vol-target"), family="xs_momentum")
class XsMomentumVolTarget(PortfolioAlgo):
    """The same momentum book behind a vol-target dial: keep the selection,
    scale the whole book down when realized volatility runs hot.

    The 20% target matches the benchmark's own normal volatility (~0.012
    daily ≈ 19% annualized), so the dial is inert in calm regimes — targeting
    below the market's vol would concede up-market return by construction —
    and only de-risks in genuine spikes (the momentum-crash failure mode the
    pass gate flagged on the raw book).
    """

    def __init__(self) -> None:
        super().__init__(
            strategy=BuyAndHold(),
            selector=MomentumSelector(lookback=60, skip=5, top_k=2),
            allocator=InverseVolatility(window=30),
            overlays=[VolTargetOverlay(target_vol=0.20, window=20)],
        )
