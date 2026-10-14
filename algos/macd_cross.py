"""Example contestant: MACD trend-follower (12/26/9)."""

from tradebot.arena import register
from tradebot.strategies import MacdTrend


@register(name="macd_cross", author="house", tags=("trend", "vectorized"))
class MacdCross(MacdTrend):
    """Long while the MACD line is above its signal line."""

    def __init__(self) -> None:
        super().__init__(fast=12, slow=26, signal=9)
