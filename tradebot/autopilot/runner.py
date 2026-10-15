"""The autopilot runner: one pass per poll inside market hours.

``tick()`` is one wake: it sends the morning brief when one is due (any
mode, see ``brief``), and if the mode is on and the market is open it runs one
engine pass (``auto`` submits, ``approve`` parks the trades as pending), then
schedules the next pass. ``run_forever`` repeats ticks with an injected sleep,
so the whole loop runs offline under a fake clock. Every engine call happens
under one lock: the loop thread and the web's taps share the engine and SQLite.
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
from .background import BackgroundMixin
from .brief import BriefMixin, MorningBrief
from .session import SessionMixin
from .state import AutopilotState, load_state, store_mode

log = logging.getLogger("tradebot.autopilot")

HALT_ERROR = "daily loss halt"


class Autopilot(ApprovalsMixin, BackgroundMixin, BriefMixin, SessionMixin):
    def __init__(self, engine, storage, *, poll_seconds: float,
                 clock: Callable[[], datetime] = utcnow,
                 sleep: Callable[[float], object] | None = None,
                 calendar: MarketCalendar | None = None,
                 is_open: schedule.IsOpen | None = None,
                 next_open: schedule.NextOpen | None = None,
                 notifier=None, brief_minutes: int | None = None,
                 scope: str | None = None) -> None:
        self.engine, self.storage = engine, storage
        # `account` keys what belongs to the account (pending lines, events);
        # `scope` keys this runner's own state (mode, anchor, brief). They
        # differ only for a headless CLI run, which must not switch the web's
        # loop on or off behind the user's back.
        self.account = engine.mode
        self.scope = scope or engine.mode
        self.poll_seconds = float(poll_seconds)
        # The config's exchange unless one is injected; `is_open`/`next_open`
        # still override it singly (a replay is "always open").
        self.calendar = calendar or get_calendar(
            getattr(engine.settings, "market", "us_equities"))
        self.clock = clock
        self.is_open = is_open or self.calendar.is_open
        self.next_open = next_open or self.calendar.next_open
        self.notifier = notifier if notifier is not None else engine.notifier
        minutes = (brief_minutes if brief_minutes is not None
                   else getattr(engine.settings, "brief_minutes_before_open", None))
        # 0 (or unset) means no brief: the Settings form offers 0 as "off".
        self.brief = MorningBrief(minutes, self.calendar) if minutes else None
        self._lock = threading.RLock()
        self._start_lock = threading.Lock()
        self._stop = threading.Event()
        # The default sleep waits on `_wake`, so a mode switch or a stop ends
        # the nap at once instead of at the next scheduled pass or brief.
        self._wake = threading.Event()
        self._sleep = sleep if sleep is not None else self._nap
        self._thread: threading.Thread | None = None
        self._running = False
        self._session: object | None = None

    # --- state -----------------------------------------------------------
    @property
    def running(self) -> bool:
        return self._running

    def state(self) -> AutopilotState:
        with self._lock:
            return load_state(self.storage, self.scope, running=self._running,
                              account=self.account)

    def set_mode(self, mode: str, *, expire_pending: bool = True) -> AutopilotState:
        """Switch modes. ``expire_pending=False`` (a CLI start) leaves parked
        lines alone: they may be the web user's, awaiting a tap."""
        with self._lock:
            store_mode(self.storage, self.scope, mode, self.clock())
            if mode == "off" and expire_pending:
                self._expire_pending()      # nobody is there to approve them now
            if mode == "off" and self.brief is None:   # with a brief, "off" still briefs
                self._stop.set()
            self._wake.set()
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
            self._maybe_brief(now)
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
            self._begin_session(day)
        if mode != "approve":
            self._expire_pending()          # nobody approves under `auto`
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
        if outcome.halted:
            self._halt()
        elif mode == "approve":
            outcome.batch_id = self._park(outcome.proposal, now)

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
                if state is not None and state.mode == "off" and self.brief is None:
                    break
                if max_ticks is None or ticks < max_ticks:
                    self._sleep(schedule.wait_seconds(
                        self.clock(), self._wake_at(state), self.poll_seconds))
        finally:
            self._running = False
        return ticks

    def _wake_at(self, state: AutopilotState | None) -> datetime | None:
        """The earlier of the next pass (when on) and the next brief; None
        (retry after one poll) when the tick itself failed."""
        if state is None:
            return None
        with self._lock:
            times = [self._brief_wake(self.clock())] if self.brief else []
        if state.mode != "off" and state.next_pass_at:
            times.append(state.next_pass_at)
        return min(times) if times else None

    def _safe_tick(self) -> AutopilotState | None:
        """A tick that cannot kill the loop: ``tick`` records pass errors; what
        is left (e.g. the store failing) has nowhere to go but the log."""
        try:
            return self.tick()
        except Exception:  # noqa: BLE001
            log.exception("Autopilot tick failed; retrying after one poll")
            return None
