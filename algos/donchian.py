"""Example contestant: Donchian channel breakout (turtle-style trend entry)."""

from tradebot.arena import register
from tradebot.strategies import DonchianBreakout


@register(name="donchian", author="house", tags=("trend", "breakout", "vectorized"))
class Donchian(DonchianBreakout):
    """Long on a 20-bar high breakout; exit on a 10-bar low break."""

    def __init__(self) -> None:
        super().__init__(entry=20, exit=10)
