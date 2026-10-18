"""The autopilot runner: one pass per poll inside market hours.

``tick()`` is one wake: it sends the morning brief when one is due (any
mode, see ``brief``), and if the mode is on and the market is open it runs one
engine pass (``auto`` submits, ``approve`` parks the trades as pending), then
schedules the next pass. ``run_forever`` repeats ticks with an injected sleep,
so the whole loop runs offline under a fake clock. Every engine call happens
under one lock: the loop thread and the web's taps share the engine and SQLite.

This module builds the runner and owns its state; one wake lives in ``wake``
and the loop in ``loop``, mixins like ``approvals`` and ``brief``.
"""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Callable

from ..market import MarketCalendar, get_calendar
from ..models import utcnow
from . import schedule
from .approvals import ApprovalsMixin
from .background import BackgroundMixin
from .brief import BriefMixin, MorningBrief
from .loop import LoopMixin
from .session import SessionMixin
from .state import AutopilotState, load_state, store_mode
from .wake import HALT_ERROR, WakeMixin  # noqa: F401 - HALT_ERROR re-exported


class Autopilot(WakeMixin, LoopMixin, ApprovalsMixin, BackgroundMixin, BriefMixin, SessionMixin):
    def __init__(self, engine, storage, *, poll_seconds: float,
                 clock: Callable[[], datetime] = utcnow,
                 sleep: Callable[[float], object] | None = None,
                 calendar: MarketCalendar | None = None,
                 is_open: schedule.IsOpen | None = None,
                 next_open: schedule.NextOpen | None = None,
                 notifier=None, brief_minutes: int | None = None,
                 scope: str | None = None, links_persist: bool = False) -> None:
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
        # `links_persist`: the push's links are signed with a key that survives
        # restarts (TRADEBOT_WEB_TOKEN), so the stored push carries over. Else
        # a restart pushes a carried batch again: `_announced_here` is empty.
        self.links_persist = links_persist
        self._announced_here: set[int] = set()

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
