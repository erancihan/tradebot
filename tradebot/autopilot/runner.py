"""The autopilot runner: one pass per poll inside market hours.

``tick()`` is one wake: if the mode is on and the market is open it runs one
engine pass (``auto`` submits, ``approve`` parks the trades as pending), then
schedules the next pass. ``run_forever`` repeats ticks with an injected sleep,
so the whole loop runs offline under a fake clock, the same pattern as the
season daemon. Every engine call happens under one lock, because the loop
thread and the web's approve taps share the engine and its SQLite connection.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Callable

from ..market import MarketCalendar, get_calendar
from ..models import utcnow
from . import schedule
from .approvals import ApprovalsMixin
from .state import AutopilotState, load_state, store_mode

log = logging.getLogger("tradebot.autopilot")

HALT_ERROR = "daily loss halt"


class Autopilot(ApprovalsMixin):
    def __init__(self, engine, storage, *, poll_seconds: float,
                 clock: Callable[[], datetime] = utcnow,
                 sleep: Callable[[float], object] | None = None,
                 calendar: MarketCalendar | None = None,
                 is_open: schedule.IsOpen | None = None,
                 next_open: schedule.NextOpen | None = None,
                 notifier=None) -> None:
        self.engine, self.storage = engine, storage
        self.scope = engine.mode
        self.poll_seconds = float(poll_seconds)
        # The config's exchange unless one is injected; `is_open`/`next_open`
        # still override it singly (a replay is "always open").
        self.calendar = calendar or get_calendar(
            getattr(engine.settings, "market", "us_equities"))
        self.clock = clock
        self.is_open = is_open or self.calendar.is_open
        self.next_open = next_open or self.calendar.next_open
        self.notifier = notifier if notifier is not None else engine.notifier
        self._lock = threading.RLock()
        self._stop = threading.Event()
        # The default sleep is the stop event's wait, so "off" wakes the loop.
        self._sleep = sleep if sleep is not None else self._stop.wait
        self._thread: threading.Thread | None = None
        self._running = False
        self._session: object | None = None

    # --- state -----------------------------------------------------------
    @property
    def running(self) -> bool:
        return self._running

    def state(self) -> AutopilotState:
        with self._lock:
            return load_state(self.storage, self.scope, running=self._running)

    def set_mode(self, mode: str) -> AutopilotState:
        with self._lock:
            store_mode(self.storage, self.scope, mode, self.clock())
            if mode == "off":
                self._expire_pending()      # nobody is there to approve them now
                self._stop.set()
            return self.state()

    def _set(self, **values) -> None:
        self.storage.set_autopilot_values(self.scope, {
            k: v.isoformat() if isinstance(v, datetime) else v for k, v in values.items()})

    # --- one wake --------------------------------------------------------
    def tick(self) -> AutopilotState:
        """One wake: a pass when the mode is on and the market open, then the
        next pass time. An exception is recorded, never raised."""
        with self._lock:
            now = self.clock()
            mode = self.state().mode
            if mode != "off":
                if self.is_open(now):
                    self._pass(mode, now)
                self._set(next_pass_at=schedule.next_pass(
                    now, self.poll_seconds, self.is_open, self.next_open))
            return self.state()

    def _pass(self, mode: str, now: datetime) -> None:
        day = schedule.session_day(now, self.calendar.timezone)
        if day != self._session:            # a new trading day: a new loss budget
            self.engine.reset_session()
            self._session = day
        self._expire_pending()              # the last batch is stale: replaced
        try:
            outcome = self.engine.step(submit=(mode == "auto"), now=now)
        except Exception as exc:  # noqa: BLE001 - the loop must outlive a bad pass
            log.exception("Autopilot pass failed")
            self._set(last_pass_at=now, last_error=f"{type(exc).__name__}: {exc}")
            return
        if outcome.market_closed:
            return
        self._set(last_pass_at=now, last_error=None)
        if outcome.halted:
            self._halt()
        elif mode == "approve":
            self._announce_pending(outcome.batch_id)

    def _halt(self) -> None:
        store_mode(self.storage, self.scope, "off", self.clock())
        self._set(last_error=HALT_ERROR)
        self._expire_pending()
        self._notify({"type": "autopilot_off", "reason": "daily_loss"})

    def _notify(self, event: dict) -> None:
        try:
            self.notifier.send({"mode": self.scope, **event})
        except Exception:  # an observer never breaks the loop
            log.exception("Notifier failed for event %s", event.get("type"))

    # --- the loop --------------------------------------------------------
    def run_forever(self, max_ticks: int | None = None) -> int:
        """Tick, sleep until the next pass, repeat; returns the ticks run.
        Ends when the mode is off, on ``stop()``, or after ``max_ticks``."""
        self._running = True
        ticks = 0
        try:
            while (max_ticks is None or ticks < max_ticks) and not self._stop.is_set():
                state = self._safe_tick()
                ticks += 1
                if state is not None and state.mode == "off":
                    break
                if max_ticks is None or ticks < max_ticks:
                    self._sleep(schedule.wait_seconds(
                        self.clock(), state.next_pass_at if state else None,
                        self.poll_seconds))
        finally:
            self._running = False
        return ticks

    def _safe_tick(self) -> AutopilotState | None:
        """A tick that cannot kill the loop: a pass error is already recorded
        by ``tick``; this catches what is left (e.g. the store itself failing),
        which has nowhere to be recorded but the log."""
        try:
            return self.tick()
        except Exception:  # noqa: BLE001
            log.exception("Autopilot tick failed; retrying after one poll")
            return None

    def start(self) -> bool:
        """Run the loop on a background thread, once. Returns whether it started."""
        if self._thread is not None and self._thread.is_alive():
            if not self._stop.is_set():
                return False
            self._thread.join()             # an "off" is winding down: let it finish
        self._stop.clear()
        self._running = True
        self._thread = threading.Thread(target=self.run_forever, name="autopilot",
                                        daemon=True)
        self._thread.start()
        return True

    def stop(self, timeout: float | None = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
