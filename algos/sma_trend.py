"""Example contestant: a vectorised trend-follower (reuses the Strategy base)."""

from tradebot.arena import register
from tradebot.strategies import SmaCrossover


@register(name="sma_trend", author="house", tags=("trend", "vectorized"))
class SmaTrend(SmaCrossover):
    """Fast/slow SMA crossover; long while fast > slow, else flat."""

    def __init__(self) -> None:
        super().__init__(fast=10, slow=30)
