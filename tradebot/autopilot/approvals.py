"""Approve-first: the user's taps on parked trades, and their expiry.

An approval submits only what the approver saw. It is refused outright while
the market is closed (a DAY market order would queue for the open at prices
nobody saw) and once the lines are older than one poll interval (their sizing
prices have moved): both expire the batch, never execute it. A line a refresh
grew past ``GROWTH_TOLERANCE`` of what was shown (the push the link came from,
or the page's ``seen``) stays pending: the newest push or the refreshed page
shows its new size. A line whose position changed since the pass is expired
(``engine.pending``); a line the broker refused stays pending and is reported.

Parking a pass's trades and pushing them live in ``parking``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ..engine import pending
from .parking import GROWTH_TOLERANCE, grew_past  # noqa: F401 - re-exported


@dataclass
class ApprovalResult:
    """What one approval (or a link's Skip) did, in enough detail to say why
    a line was not submitted."""
    submitted: int = 0
    rejected: int = 0
    held: list[str] = field(default_factory=list)       # re-sized past what was shown
    moved: list[str] = field(default_factory=list)      # position changed: expired
    failed: list[tuple[str, str]] = field(default_factory=list)   # (symbol, error)
    closed: bool = False                                 # market closed: all expired
    stale: bool = False                                  # older than one poll: expired


def failure_text(failed: list[tuple[str, str]]) -> str | None:
    """``last_error`` for orders the broker refused, naming each symbol."""
    if not failed:
        return None
    return "order failed: " + "; ".join(f"{sym} ({err})" for sym, err in failed)


class ForeignBatch(LookupError):
    """A signed link named a batch recorded under another account."""


class ApprovalsMixin:
    """Mixed into ``Autopilot``; uses its engine, storage, clock and lock."""

    def approve(self, line_ids: list[int], seen: dict | None = None) -> int:
        """Submit the chosen pending lines; returns how many were submitted."""
        return self.approve_detail(line_ids, seen).submitted

    def approve_detail(self, line_ids: list[int],
                       seen: dict | None = None) -> ApprovalResult:
        """Submit the chosen pending lines; see the module docstring.

        ``seen`` is what the approver was shown, ``{line id: notional}``: a
        line missing from it, or grown past the tolerance, is held back.
        ``None`` skips that check, for callers that showed no sizes (an older
        page, the CLI's tests); the staleness check still bounds them."""
        with self._lock:
            now = self.clock()
            if not self.is_open(now):
                self._expire_pending()
                return ApprovalResult(closed=True)
            wanted = {int(i) for i in line_ids}
            rows = [ln for ln in self._waiting_lines() if ln["id"] in wanted]
            if not rows:
                return ApprovalResult()
            if self._pending_is_stale():
                self._expire_pending()
                return ApprovalResult(stale=True)
            held: list[str] = []
            if seen is not None:
                shown = {int(k): float(v) for k, v in seen.items()}
                grown = {ln["id"] for ln in rows if ln["id"] not in shown
                         or grew_past(ln["notional"], shown[ln["id"]])}
                held = [ln["symbol"] for ln in rows if ln["id"] in grown]
                rows = [ln for ln in rows if ln["id"] not in grown]
            # Stamped with the autopilot's clock: a replay's reads its bars.
            done = pending.submit_stored(self.engine, [ln["id"] for ln in rows], now=now)
            if done.failed:
                self._report_failed(done.failed)
            return ApprovalResult(submitted=len(done.actions), held=held,
                                  moved=done.moved, failed=done.failed)

    def reject(self, line_ids: list[int]) -> int:
        """Mark the chosen pending lines rejected; nothing is submitted."""
        with self._lock:
            chosen = self._pending_ids(line_ids)
            if chosen:
                self.storage.set_line_status(chosen, "rejected")
            return len(chosen)

    def act_on_batch(self, batch_id: int, verb: str, exp: int) -> ApprovalResult:
        """A signed link's command: approve or reject one batch's still-pending
        lines of this account. ``exp`` (the link's expiry) names the push it
        came from: an approval holds each line to that push's size. The lookup
        and the act share the lock, so a pass cannot replace the batch in
        between. A live account is never approved by link (it rode through the
        ntfy topic); another account's batch raises ``ForeignBatch``."""
        with self._lock:
            if verb == "approve" and self.account == "live":
                return ApprovalResult()
            owner = self.storage.batch_mode(batch_id)
            if owner is not None and owner != self.account:
                raise ForeignBatch(f"batch {batch_id} belongs to {owner}")
            ids = [ln["id"] for ln in
                   self.storage.pending_lines_in_batch(batch_id, self.account)]
            if not ids:
                return ApprovalResult()
            if verb != "approve":
                return ApprovalResult(rejected=self.reject(ids))
            return self.approve_detail(ids, seen=self._shown_by_push(batch_id, exp))

    def _report_failed(self, failed: list[tuple[str, str]]) -> None:
        """A refused order is never silent: the page's error line and a push."""
        text = failure_text(failed)
        self._set(last_error=text)
        self._notify({"type": "order_failed", "symbols": [s for s, _ in failed],
                      "message": text})

    def _waiting_lines(self) -> list[dict]:
        """The pending lines minus any the broker already has (their mark is
        retried first): those are never asked about, expired or sent again."""
        pending.settle_sent(self.engine)
        sent = getattr(self.engine, "_sent_line_ids", ())
        return [ln for ln in self.storage.pending_lines(self.account) if ln["id"] not in sent]

    def _pending_ids(self, line_ids: list[int]) -> list[int]:
        wanted = {int(i) for i in line_ids}
        return [ln["id"] for ln in self._waiting_lines() if ln["id"] in wanted]

    def _pending_is_stale(self) -> bool:
        lines = self._waiting_lines()
        if not lines:
            return False
        oldest = min(datetime.fromisoformat(ln["created_at"]) for ln in lines)
        return self.clock() - oldest > timedelta(seconds=self.poll_seconds)

    def _expire_pending(self) -> int:
        ids = [ln["id"] for ln in self._waiting_lines()]
        if ids:
            self.storage.set_line_status(ids, "expired")
        return len(ids)
