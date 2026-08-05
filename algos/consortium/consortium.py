"""The consortium: every other contestant in the folder, blended into one book.

It competes as an ordinary entry against the same baseline over the same
gauntlet as everything else. Being the framework earns it no exemption — if a
panel of twelve algorithms cannot beat holding the market, that is a result
worth having, and the only way to find out is to make it run the gauntlet.

Two variants share the ``consortium`` family so the journal counts their
attempts together:

- ``consortium`` — equal voice. The baseline any adaptive scheme must beat.
- ``consortium_hedge`` — exponential weights on each member's realised P&L,
  with a floor so a silenced member can recover.

**Read the caveat before quoting either.** The members are mostly trend and
mean-reversion variants over one equity-beta pool. Averaging correlated members
reduces the noise in the estimate, not the systematic exposure — this panel is
closer to one strategy wearing many hats than to a diversified committee. The
binding constraint on a consortium being *worth* anything is member diversity,
which is a roster problem, not a combiner problem.
"""

from pathlib import Path

from tradebot.arena import PortfolioAlgo, register
from tradebot.arena.loader import discover
from tradebot.arena.panel import eligible_members
from tradebot.consortium import Consortium, build_voice

#: The field lives one level up. `loader._expand` globs non-recursively, so
#: `--algos ./algos` does NOT pick this file up: the consortium is opt-in,
#: exactly like the canaries, and for the same reason — it is expensive by
#: construction (it costs the sum of its members) and would otherwise slow every
#: ordinary tournament and blow the default per-contestant time budget.
FIELD = Path(__file__).resolve().parent.parent


def _members():
    """Every contestant in the field except consortia themselves.

    Self-exclusion is not optional: a consortium that loaded itself would
    recurse until the process died. It is guarded twice — structurally, because
    this file sits in a subdirectory the non-recursive glob never reaches, and
    by a marker attribute, so moving the file back cannot reintroduce the loop.
    The marker is not a name match: renaming a contestant must not be able to
    break this.
    """
    found, _errors = discover([str(FIELD)])
    return eligible_members(found)


class _ConsortiumBase(PortfolioAlgo):
    voice_name = "equal"
    voice_params: dict = {}

    def __init__(self) -> None:
        panel = Consortium(_members(), voice=build_voice(self.voice_name,
                                                         self.voice_params))
        # The consortium is its own signal AND its own weighting: the sign of
        # the blended book sets the target, its magnitude sets conviction. It
        # supplies a symbol-aware policy because the consensus is a table
        # indexed by (bar, symbol), which a plain Strategy cannot express.
        super().__init__(strategy=panel, allocator=panel)


@register(name="consortium", author="house",
          tags=("consortium", "ensemble", "portfolio"), family="consortium")
class EqualConsortium(_ConsortiumBase):
    """Blend every other contestant's book, equally weighted."""


@register(name="consortium_hedge", author="house",
          tags=("consortium", "ensemble", "adaptive", "portfolio"),
          family="consortium")
class HedgeConsortium(_ConsortiumBase):
    """The same blend, with voice earned from each member's realised P&L.

    eta=2.0 is a declared researcher degree of freedom, not a fitted value: it
    is the learning rate at which a member roughly halves its voice after a
    ~35% relative drawdown against the panel. The 2% floor keeps every member
    alive so a recovery is visible.
    """

    voice_name = "hedge"
    voice_params = {"eta": 2.0, "floor": 0.02}


# The marker the loader-side filter looks for; see `arena.panel.is_consortium`.
EqualConsortium.is_consortium = True
HedgeConsortium.is_consortium = True
