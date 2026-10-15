"""Approve-first: the user's taps on pending trades, and their expiry.

A pending batch is sized at the prices of the pass that made it. Once it is
older than one poll interval those prices have moved, so it is expired, never
executed: by the next pass (which replaces it) or by a late approval.
"""

from __future__ import annotations

from datetime import datetime, timedelta


class ForeignBatch(LookupError):
    """A signed link named a batch recorded under another account."""


class ApprovalsMixin:
    """Mixed into ``Autopilot``; uses its engine, storage, clock and lock."""

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

    def _announce_pending(self, batch_id: int | None) -> None:
        lines = self.storage.pending_lines(self.account)
        if not lines:
            return
        self._notify({
            "type": "pending_trades", "batch_id": batch_id, "count": len(lines),
            "lines": [{"id": ln["id"], "symbol": ln["symbol"], "action": ln["action"],
                       "qty": abs(ln["order_qty"]), "notional": ln["notional"]}
                      for ln in lines],
        })
