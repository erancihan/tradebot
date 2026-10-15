"""Approve-first: the user's taps on pending trades, and their expiry.

A pending batch is sized at the prices of the pass that made it. Once it is
older than one poll interval those prices have moved, so it is expired, never
executed: by the next pass (which replaces it) or by a late approval.
"""

from __future__ import annotations

from datetime import datetime, timedelta


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
            return len(self.engine.submit_lines(chosen))

    def reject(self, line_ids: list[int]) -> int:
        """Mark the chosen pending lines rejected; nothing is submitted."""
        with self._lock:
            chosen = self._pending_ids(line_ids)
            if chosen:
                self.storage.set_line_status(chosen, "rejected")
            return len(chosen)

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
