"""Example contestant: a regime-switching cross-sectional book.

Defense by *rotation* rather than scaling. In calm regimes the book holds the
top trailing performers; when the pool's realized volatility spikes into a
storm it rotates into the calmest names instead — the book stays invested, just
in different names. Contrast ``xs_momentum_vt``, which keeps the same names and
dials the whole book down. Inverse-vol weighted so risk (not dollars) is spread.
"""

from tradebot.allocation import InverseVolatility
from tradebot.arena import PortfolioAlgo, register
from tradebot.selection import RegimeSwitchSelector
from tradebot.strategies import BuyAndHold


@register(name="xs_regime", author="house",
          tags=("portfolio", "momentum", "regime"), family="xs_regime")
class XsRegime(PortfolioAlgo):
    """Momentum top-2 in calm regimes; rotate to the 2 calmest names in a storm."""

    def __init__(self) -> None:
        super().__init__(
            strategy=BuyAndHold(),
            selector=RegimeSwitchSelector(
                lookback=60, skip=5, top_k=2, vol_window=30, storm_vol=0.25,
            ),
            allocator=InverseVolatility(window=30),
        )
