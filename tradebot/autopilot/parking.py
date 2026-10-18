"""Approve-first parking: storing a pass's trades, and announcing them.

A pass that proposes the same ``(symbol, action)`` trades as the batch it
parked last carries that batch over: its pending lines and holds are re-sized
in place, rejected lines stay rejected, and the batch id (so an earlier push's
link) survives. A rejection (even of every line) holds until the proposal
changes or the trading day ends; an all-holds pass in between is a change, so
the same trades after it are asked again. A batch is pushed once, then again
as a reminder when its links are about to die (``links.ttl_seconds`` after the
push, or the push's own expiry if sooner), or at once when a refresh grows a
line past ``GROWTH_TOLERANCE`` of what the push said. Every push's sizes are
kept under its link expiry, so a tap on an older push's button can be held to
what that push showed (``approvals``).
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from ..engine import pending
from . import schedule
from .links import ttl_seconds

#: Line statuses that make up the shape of a waiting batch: a rejected line
#: still counts, so the same proposal never asks about it again.
_SHAPE_STATUSES = ("pending", "rejected")

#: A carried line re-sized to more than this share above what the last push
#: said is pushed again at once, and an approval of it against an older push
#: (or an older page) is refused: an approval must mean what was shown.
GROWTH_TOLERANCE = 0.10

#: Where a headless ``tradebot run --autopilot`` keeps its state.
CLI_SCOPE_PREFIX = "cli_"


def _trades(lines) -> set[tuple[str, str]]:
    return {(ln.symbol, ln.action) for ln in lines if ln.order_qty and not ln.skipped}


def grew_past(notional: float, shown: float) -> bool:
    return abs(notional) > abs(shown) * (1 + GROWTH_TOLERANCE)


class ParkingMixin:
    """Mixed into ``Autopilot``; uses its engine, storage, clock and scope."""

    _announced_here: set[int]
    links_persist: bool

    def _park(self, proposal, now: datetime, day: date) -> int | None:
        """Store an approve pass's proposal: carry the parked batch over when
        the trades are unchanged, else replace it. Push when one is due."""
        batch_id = self._carried_batch(proposal, day)
        if batch_id is None:
            self._expire_pending()
            batch_id = self._repeated_holds(proposal, day)
            if batch_id is None:
                batch_id = pending.record_pending(self.engine, proposal)
        else:
            self.storage.refresh_pending_batch(batch_id, proposal, self.account)
        self._set(parked_batch=str(batch_id))
        if self._announce_due(batch_id, now):
            self._announce(batch_id, now)
        return batch_id

    def _carried_batch(self, proposal, day: date) -> int | None:
        """The waiting batch when this runner parked it last, ``proposal``
        trades exactly what it asks and it was last refreshed this session
        day, else None. An all-rejected batch still waits: Skip must not bring
        the same trades back, until a different answer (holds) came between."""
        waiting = self.storage.waiting_batch(self.account)
        if waiting is None:
            return None
        batch_id = waiting["id"]
        if self.storage.autopilot_values(self.scope).get("parked_batch") != str(batch_id):
            return None
        if {ln["batch_id"] for ln in self.storage.pending_lines(self.account)} - {batch_id}:
            return None
        at = datetime.fromisoformat(waiting["created_at"])
        if schedule.session_day(at, self.calendar.timezone) != day:
            return None                     # a rejection ends with the trading day
        lines = self.storage.batch_lines(batch_id, self.account)
        if any(ln["status"] == "expired" for ln in lines):
            return None
        asked = {(ln["symbol"], ln["action"]) for ln in lines
                 if ln["status"] in _SHAPE_STATUSES and ln["order_qty"]}
        return batch_id if asked == _trades(proposal.lines) else None

    def _repeated_holds(self, proposal, day: date) -> int | None:
        """The newest batch, refreshed in place, when it and ``proposal`` are
        the same all-holds answer of this session day; else None. A quiet
        market would otherwise add one History batch per poll."""
        if _trades(proposal.lines):
            return None
        head = self.storage.latest_proposal(self.account)
        if head is None or any(ln["order_qty"] for ln in head["lines"]):
            return None
        at = datetime.fromisoformat(head["created_at"])
        if schedule.session_day(at, self.calendar.timezone) != day:
            return None
        if ({(ln["symbol"], ln["action"]) for ln in head["lines"]}
                != {(ln.symbol, ln.action) for ln in proposal.lines}):
            return None
        self.storage.refresh_pending_batch(head["id"], proposal, self.account)
        return head["id"]

    def _announce_due(self, batch_id: int | None, now: datetime) -> bool:
        raw = self.storage.autopilot_values(self.scope)
        if batch_id is None or raw.get("announced_batch") != str(batch_id):
            return True
        # A key that survives restarts keeps the stored push's buttons alive.
        if not self.links_persist and batch_id not in self._announced_here:
            return True
        last, exp = raw.get("announced_at"), raw.get("announced_exp")
        if last is None or now - datetime.fromisoformat(last) >= timedelta(
                seconds=ttl_seconds(self.poll_seconds)):
            return True
        # The phone's buttons die at the push's own expiry, whatever the poll
        # (and so the ttl) has become since.
        if exp is not None and now.timestamp() >= int(exp):
            return True
        return self._grew_past_shown(json.loads(raw.get("announced_notional") or "{}"))

    def _grew_past_shown(self, shown: dict[str, float]) -> bool:
        """Did a refresh grow a pending line past what the last push said?"""
        for ln in self._waiting_lines():
            was = shown.get(str(ln["id"]))
            if was is not None and grew_past(ln["notional"], was):
                return True
        return False

    def _announce(self, batch_id: int, now: datetime) -> None:
        """Push the batch and keep what this push showed under its link expiry.
        The expiry names the push, so two pushes of one batch never share one
        (a second push within the same second expires a second later)."""
        raw = self.storage.autopilot_values(self.scope)
        pushes = (json.loads(raw.get("announced_pushes") or "{}")
                  if raw.get("announced_batch") == str(batch_id) else {})
        exp = max([int(now.timestamp()) + ttl_seconds(self.poll_seconds),
                   *(int(k) + 1 for k in pushes)])
        shown = self._announce_pending(batch_id, exp)
        self._announced_here.add(batch_id)
        pushes = {k: v for k, v in pushes.items() if int(k) >= now.timestamp()}
        pushes[str(exp)] = shown
        self._set(announced_batch=str(batch_id), announced_at=now, announced_exp=str(exp),
                  announced_notional=json.dumps(shown), announced_pushes=json.dumps(pushes))

    def _shown_by_push(self, batch_id: int, exp: int) -> dict[int, float]:
        """What the push whose links expire at ``exp`` showed for ``batch_id``
        (``{line id: notional}``), or {} for a push not on record. Looked up in
        this runner's scope and the headless CLI's, whose links the web serves."""
        for scope in dict.fromkeys((self.scope, self.account,
                                    CLI_SCOPE_PREFIX + self.account)):
            raw = self.storage.autopilot_values(scope)
            if raw.get("announced_batch") != str(batch_id):
                continue
            shown = json.loads(raw.get("announced_pushes") or "{}").get(str(int(exp)))
            if shown is not None:
                return {int(k): float(v) for k, v in shown.items()}
        return {}

    def _announce_pending(self, batch_id: int | None, exp: int) -> dict[str, float]:
        """Push the pending lines; returns what was shown (``{line id: notional}``).
        ``link_exp`` is the expiry the push's signed links carry."""
        lines = self._waiting_lines()
        if not lines:
            return {}
        self._notify({
            "type": "pending_trades", "batch_id": batch_id, "count": len(lines),
            "link_exp": exp,
            "lines": [{"id": ln["id"], "symbol": ln["symbol"], "action": ln["action"],
                       "qty": abs(ln["order_qty"]), "notional": ln["notional"]}
                      for ln in lines],
        })
        return {str(ln["id"]): float(ln["notional"]) for ln in lines}
