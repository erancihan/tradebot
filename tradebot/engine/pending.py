"""Approve-first passes: park a proposal as pending, submit chosen lines later.

The autopilot's ``approve`` mode splits one rebalance pass in two. The pass
stores its proposal with actionable lines ``pending``; the user's approval
submits exactly those stored lines through the same ``submit_line`` the
automatic path uses, so an approved trade and an automatic one are the same
order.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, fields

from ..advisor import Proposal, ProposalLine
from . import orders
from .orders import RebalanceAction

log = logging.getLogger("tradebot.engine")

_LINE_FIELDS = tuple(f.name for f in fields(ProposalLine) if f.name != "skipped")


@dataclass
class PassOutcome:
    """What one pass did, so a supervisor can react to a halt or a closed market."""
    actions: list[RebalanceAction] = field(default_factory=list)
    proposal: Proposal | None = None
    batch_id: int | None = None          # the pending batch, when not submitting
    halted: bool = False                 # the daily-loss breaker tripped
    market_closed: bool = False


def record_pending(engine, proposal: Proposal) -> int | None:
    """Store the proposal; trades wait as ``pending``, holds are kept as record."""
    if engine.storage is None:
        raise RuntimeError("an approve-first pass needs storage to park its trades")
    return engine.storage.record_proposal(proposal, engine.mode, status="pending",
                                          hold_status="suggested")


def submit_stored(engine, line_ids: list[int]) -> list[RebalanceAction]:
    """Submit the given pending lines and mark each one ``submitted``.

    A line that is no longer pending (expired, rejected, already submitted,
    or another account's) is ignored, so a double tap cannot order twice.
    """
    rows = engine.storage.proposal_lines(line_ids, engine.mode, status="pending")
    actions: list[RebalanceAction] = []
    for row in rows:
        line = ProposalLine(**{name: row[name] for name in _LINE_FIELDS})
        try:
            actions.append(orders.submit_line(engine, line))
        except Exception:  # one bad symbol must not block the rest of the batch
            log.exception("Approved line %s (%s) failed to submit", row["id"], line.symbol)
            continue
        engine.storage.set_line_status([row["id"]], "submitted")
    return actions
