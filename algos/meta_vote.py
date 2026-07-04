"""Example contestant: majority vote across a mixed trend/reversion roster."""

from tradebot.arena import register
from tradebot.strategies import EnsembleVote


@register(name="meta_vote", author="house", tags=("meta", "ensemble", "vectorized"))
class MetaVote(EnsembleVote):
    """Long/short only when a strict majority of the roster agrees."""

    def __init__(self) -> None:
        super().__init__()
