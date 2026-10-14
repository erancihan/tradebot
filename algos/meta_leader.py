"""Example contestant: greedy bandit over a mixed trend/reversion roster."""

from tradebot.arena import register
from tradebot.strategies import FollowTheLeader


@register(name="meta_leader", author="house", tags=("meta", "adaptive", "vectorized"))
class MetaLeader(FollowTheLeader):
    """Each bar, trade whatever sub-strategy won the trailing 40 bars."""

    def __init__(self) -> None:
        super().__init__(window=40)
