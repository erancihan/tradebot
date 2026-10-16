"""Approve-first: parking a pass's trades, the user's taps, and their expiry.

A pass that proposes the same ``(symbol, action)`` trades as the waiting batch
carries that batch over: its pending lines and holds are re-sized in place,
rejected lines stay rejected, and the batch id (so an earlier push's link)
survives. A rejection (even of every line) holds until the proposal changes
or the trading day ends. A changed proposal expires the batch and records a
new one. A batch is pushed once, then again only as a reminder every
``links.ttl_seconds`` (the link lifetime, so a push's buttons work until the
next one arrives). A restart pushes it again only when the link key is
per-process (``links_persist`` False): the old push's buttons died with it.

The lines are sized at the prices of the pass that last touched them. Once
they are older than one poll interval those prices have moved, so a late
approval expires them, never executes them.
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
#: said is pushed again at once: an approval must mean what was shown.
GROWTH_TOLERANCE = 0.10


def _trades(lines) -> set[tuple[str, str]]:
    return {(ln.symbol, ln.action) for ln in lines if ln.order_qty and not ln.skipped}


class ForeignBatch(LookupError):
    """A signed link named a batch recorded under another account."""


class ApprovalsMixin:
    """Mixed into ``Autopilot``; uses its engine, storage, clock and lock."""

    _announced_here: set[int]
    links_persist: bool

    def approve(self, line_ids: list[int]) -> int:
        """Submit the chosen pending lines; returns how many were submitted.
        A stale batch is expired instead and nothing is submitted."""
        with self._lock:
            chosen = self._pending_ids(line_ids)
            if not chosen:
                return 0
            if self._pending_is_stale():
                self._expire_pending()
                return 0
            # Stamped with the autopilot's clock: a replay's reads its bars.
            return len(self.engine.submit_lines(chosen, now=self.clock()))

    def reject(self, line_ids: list[int]) -> int:
        """Mark the chosen pending lines rejected; nothing is submitted."""
        with self._lock:
            chosen = self._pending_ids(line_ids)
            if chosen:
                self.storage.set_line_status(chosen, "rejected")
            return len(chosen)

    def act_on_batch(self, batch_id: int, verb: str) -> int:
        """A signed link's command: approve or reject one batch's still-pending
        lines of this account. The lookup and the act share the lock, so a pass
        cannot replace the batch in between. A live account is never approved
        by link (it rode through the ntfy topic); another account's batch
        raises ``ForeignBatch`` rather than reporting 0 acted on."""
        with self._lock:
            if verb == "approve" and self.account == "live":
                return 0
            owner = self.storage.batch_mode(batch_id)
            if owner is not None and owner != self.account:
                raise ForeignBatch(f"batch {batch_id} belongs to {owner}")
            ids = [ln["id"] for ln in
                   self.storage.pending_lines_in_batch(batch_id, self.account)]
            if not ids:
                return 0
            return self.approve(ids) if verb == "approve" else self.reject(ids)

    def _park(self, proposal, now: datetime, day: date) -> int | None:
        """Store an approve pass's proposal: carry the waiting batch over when
        the trades are unchanged, else replace it. Push a new batch, or a
        carried one whose last push is a link lifetime old."""
        batch_id = self._carried_batch(proposal, day)
        if batch_id is None:
            self._expire_pending()
            batch_id = pending.record_pending(self.engine, proposal)
        else:
            self.storage.refresh_pending_batch(batch_id, proposal, self.account)
        if self._announce_due(batch_id, now):
            shown = self._announce_pending(batch_id)
            self._announced_here.add(batch_id)
            self._set(announced_batch=str(batch_id), announced_at=now,
                      announced_notional=json.dumps(shown))
        return batch_id

    def _carried_batch(self, proposal, day: date) -> int | None:
        """The waiting batch when ``proposal`` trades exactly what it asks and
        it was last refreshed this session day, else None. An all-rejected
        batch still waits: Skip must not bring the same trades back."""
        waiting = self.storage.waiting_batch(self.account)
        if waiting is None:
            return None
        batch_id = waiting["id"]
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

    def _announce_due(self, batch_id: int | None, now: datetime) -> bool:
        raw = self.storage.autopilot_values(self.scope)
        if batch_id is None or raw.get("announced_batch") != str(batch_id):
            return True
        # A key that survives restarts keeps the stored push's buttons alive.
        if not self.links_persist and batch_id not in self._announced_here:
            return True
        last = raw.get("announced_at")
        if (last is None or now - datetime.fromisoformat(last)
                >= timedelta(seconds=ttl_seconds(self.poll_seconds))):
            return True
        return self._grew_past_shown(json.loads(raw.get("announced_notional") or "{}"))

    def _grew_past_shown(self, shown: dict[str, float]) -> bool:
        """Did a refresh grow a pending line past what the last push said?"""
        for ln in self.storage.pending_lines(self.account):
            was = shown.get(str(ln["id"]))
            if was is not None and abs(ln["notional"]) > abs(was) * (1 + GROWTH_TOLERANCE):
                return True
        return False

    def _pending_ids(self, line_ids: list[int]) -> list[int]:
        wanted = {int(i) for i in line_ids}
        return [ln["id"] for ln in self.storage.pending_lines(self.account)
                if ln["id"] in wanted]

    def _pending_is_stale(self) -> bool:
        lines = self.storage.pending_lines(self.account)
        if not lines:
            return False
        oldest = min(datetime.fromisoformat(ln["created_at"]) for ln in lines)
        return self.clock() - oldest > timedelta(seconds=self.poll_seconds)

    def _expire_pending(self) -> int:
        ids = [ln["id"] for ln in self.storage.pending_lines(self.account)]
        if ids:
            self.storage.set_line_status(ids, "expired")
        return len(ids)

    def _announce_pending(self, batch_id: int | None) -> dict[str, float]:
        """Push the pending lines; returns what was shown (``{line id: notional}``)."""
        lines = self.storage.pending_lines(self.account)
        if not lines:
            return {}
        self._notify({
            "type": "pending_trades", "batch_id": batch_id, "count": len(lines),
            "lines": [{"id": ln["id"], "symbol": ln["symbol"], "action": ln["action"],
                       "qty": abs(ln["order_qty"]), "notional": ln["notional"]}
                      for ln in lines],
        })
        return {str(ln["id"]): float(ln["notional"]) for ln in lines}
