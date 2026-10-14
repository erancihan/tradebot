"""Example contestant: Bollinger-band dip buyer (mean reversion)."""

from tradebot.arena import register
from tradebot.strategies import BollingerReversion


@register(name="bollinger_dip", author="house", tags=("mean-reversion", "vectorized"))
class BollingerDip(BollingerReversion):
    """Buy a close below the lower 20/2 band; exit at the middle band."""

    def __init__(self) -> None:
        super().__init__(window=20, num_std=2.0)
