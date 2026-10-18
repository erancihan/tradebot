"""One autopilot wake: the brief check, then a pass when the mode is on.

Split from ``runner.py`` (which keeps construction and state) so one wake's
decisions read on their own: ``tick`` under the lock, ``_pass`` running one
engine step, ``_halt`` turning the autopilot off after a daily-loss breach.
"""

from __future__ import annotations

import logging
from datetime import datetime

from ..engine import fills, pending
from . import schedule
from .state import AutopilotState, store_mode

log = logging.getLogger("tradebot.autopilot")

HALT_ERROR = "daily loss halt"


class WakeMixin:
    """Mixed into ``Autopilot``; uses its lock, clock, calendar, engine and store."""

    # --- one wake --------------------------------------------------------
    def tick(self) -> AutopilotState:
        """One wake: a pass when the mode is on and the market open, then the
        next pass time. An exception is recorded, never raised."""
        with self._lock:
            now = self.clock()
            self._maybe_brief(now)
            mode = self.state().mode
            if mode != "off":
                if self.is_open(now):
                    self._pass(mode, now)
                elif self._expire_pending():
                    # The wake after the close, or a start while closed: nothing
                    # passes until the open, the batch's sizing is dead, and a
                    # late approval must not queue for the open.
                    log.info("Market closed: expired the waiting batch")
                self._set(next_pass_at=schedule.next_pass(
                    now, self.poll_seconds, self.is_open, self.next_open))
            return self.state()

    def _pass(self, mode: str, now: datetime) -> None:
        day = schedule.session_day(now, self.calendar.timezone)
        if day != self._session:            # a new trading day: a new loss budget
            self._begin_session(day)
        if mode != "approve":
            self._expire_pending()          # nobody approves under `auto`
        fills.reconcile_quietly(self.engine, now=now)   # last pass's fills first
        pending.settle_sent(self.engine)    # a sent line's mark that failed earlier
        if self._stop.is_set():             # a reset is waiting: start no new pass
            return
        try:
            # Unrecorded: `_park` carries an unchanged batch over instead.
            outcome = self.engine.step(submit=(mode == "auto"), now=now, record=False)
        except Exception as exc:  # noqa: BLE001 - the loop must outlive a bad pass
            self._expire_pending()          # no fresh sizing: the batch is stale
            self._save_session(day)
            log.exception("Autopilot pass failed")
            self._set(last_pass_at=now, last_error=f"{type(exc).__name__}: {exc}")
            return
        self._save_session(day)
        if outcome.market_closed:
            self._expire_pending()
            return
        self._set(last_pass_at=now, last_error=None)
        if outcome.failed:                  # never silent: the error line and a push
            self._report_failed(outcome.failed)
        if outcome.halted:
            self._halt()
        elif mode == "approve" and not self._stop.is_set():
            # A stop that landed mid-pass: a newer runner may own the account.
            outcome.batch_id = self._park(outcome.proposal, now, day)

    def _halt(self) -> None:
        store_mode(self.storage, self.scope, "off", self.clock())
        self._set(last_error=HALT_ERROR)
        self._expire_pending()
        self._notify({"type": "autopilot_off", "reason": "daily_loss"})

    def _notify(self, event: dict) -> None:
        try:
            self.notifier.send({"mode": self.account, **event})
        except Exception:  # an observer never breaks the loop
            log.exception("Notifier failed for event %s", event.get("type"))
