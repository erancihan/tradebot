"""The advisor: what the engine would trade right now, without trading it.

A :class:`Proposal` is the set of signed share deltas one rebalance pass would
submit. Suggestions (the Today page) and executions (``Engine.rebalance``) are
two consumers of the same proposal, so they cannot disagree.
"""

from __future__ import annotations

from .explain import explain
from .propose import propose
from .types import Proposal, ProposalLine

__all__ = ["Proposal", "ProposalLine", "explain", "propose"]
