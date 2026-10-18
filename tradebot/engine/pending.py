"""Approve-first passes: park a proposal as pending, submit chosen lines later.

The autopilot's ``approve`` mode splits one rebalance pass in two. The pass
stores its proposal with actionable lines ``pending``; the user's approval
submits exactly those stored lines through the same ``submit_line`` the
automatic path uses, so an approved trade and an automatic one are the same
order.

An approval comes minutes after the pass, so before a line is sent its
position is read again: a line sized against a holding that has since
changed (a hand trade, a stop that fired, a fill landing late) is expired,
never sent. A stored exit against a position that is gone would otherwise
open a short, and a stored entry against one already bought would double it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, fields
from datetime import datetime
from functools import partial

from ..advisor import Proposal, ProposalLine
from . import fills, orders
from .orders import RebalanceAction

log = logging.getLogger("tradebot.engine")

_LINE_FIELDS = tuple(f.name for f in fields(ProposalLine) if f.name != "skipped")
#: Below this the held quantity equals the one the line was sized against.
_QTY_EPS = 1e-6


@dataclass
class PassOutcome:
    """What one pass did, so a supervisor can react to a halt or a closed market."""
    actions: list[RebalanceAction] = field(default_factory=list)
    proposal: Proposal | None = None
    batch_id: int | None = None          # the pending batch, when not submitting
    halted: bool = False                 # the daily-loss breaker tripped
    market_closed: bool = False
    failed: list[tuple[str, str]] = field(default_factory=list)   # (symbol, error)


@dataclass
class Submitted:
    """What one approval's submit did: the orders sent, the symbols whose
    position moved since the pass (expired unsent), the ``(symbol, error)``
    of each line the broker refused (left pending)."""
    actions: list[RebalanceAction] = field(default_factory=list)
    moved: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)


def record_pending(engine, proposal: Proposal) -> int | None:
    """Store the proposal; trades wait as ``pending``, holds are kept as record."""
    if engine.storage is None:
        raise RuntimeError("an approve-first pass needs storage to park its trades")
    return engine.storage.record_proposal(proposal, engine.mode, status="pending",
                                          hold_status="suggested")


def settle_sent(engine) -> None:
    """Retry the ``submitted`` mark of lines the broker already has (their
    first mark failed). Until it lands they stay in ``_sent_line_ids``, which
    every approval filters out, so a second tap cannot send them again."""
    sent = getattr(engine, "_sent_line_ids", None)
    if not sent or engine.storage is None:
        return
    try:
        rows = engine.storage.proposal_lines(sorted(sent), engine.mode, status="pending")
        if rows:
            engine.storage.set_line_status([r["id"] for r in rows], "submitted")
    except Exception:  # noqa: BLE001 - still locked: the set keeps guarding
        log.exception("Could not mark sent lines %s submitted; retrying later", sorted(sent))
        return
    sent.clear()


def _mark_sent(engine, line_id: int) -> None:
    engine._sent_line_ids.add(line_id)      # first: the write below may fail
    engine.storage.set_line_status([line_id], "submitted")
    engine._sent_line_ids.discard(line_id)


def _moved(held: dict, line: ProposalLine) -> bool:
    pos = held.get(line.symbol)
    qty = float(pos.qty) if pos is not None else 0.0
    return abs(qty - float(line.current_qty or 0.0)) > _QTY_EPS


def submit_stored(engine, line_ids: list[int], now: datetime | None = None) -> Submitted:
    """Submit the given pending lines and mark each one ``submitted``.

    A line that is no longer pending (expired, rejected, already submitted,
    or another account's), or already sent, is ignored, so a double tap
    cannot order twice. The mark is written the moment the broker accepts the
    order, before the order log, so a failing log write cannot leave a sent
    line ``pending``. The positions are read once, before anything is sent.
    """
    settle_sent(engine)
    rows = [r for r in engine.storage.proposal_lines(line_ids, engine.mode, status="pending")
            if r["id"] not in engine._sent_line_ids]
    out = Submitted()
    if not rows:
        return out
    pairs = [(ProposalLine(**{name: row[name] for name in _LINE_FIELDS}), row) for row in rows]
    try:
        held = engine.broker.positions()
    except Exception as exc:  # noqa: BLE001 - unknown holdings: send nothing
        log.exception("Position read failed; no approved line was sent")
        out.failed = [(line.symbol, orders.error_text(exc)) for line, _ in pairs]
        return out
    # Exits first, as an automatic pass does: a swap's sell funds its buy.
    for line, row in orders.exits_first(pairs, line=lambda pair: pair[0]):
        try:
            if _moved(held, line):
                engine.storage.set_line_status([row["id"]], "expired")
                log.warning("%s: the position changed since the pass; line %s expired",
                            line.symbol, row["id"])
                out.moved.append(line.symbol)
                continue
            out.actions.append(orders.submit_line(
                engine, line, on_submitted=partial(_mark_sent, engine, row["id"]), now=now))
        except Exception as exc:  # one bad symbol must not block the rest of the batch
            log.exception("Approved line %s (%s) failed to submit", row["id"], line.symbol)
            out.failed.append((line.symbol, orders.error_text(exc)))
    if any(a.submitted_id for a in out.actions):   # usually filled at once: one look
        fills.reconcile_quietly(engine, now=now)
    return out
