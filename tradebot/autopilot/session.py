"""The daily-loss session anchor, persisted with the autopilot state.

The breaker measures today's drawdown from the equity the first pass of the
day saw. Held only in memory, that anchor was lost on every restart and every
Settings save (which rebuilds the engine), and the new engine re-anchored at
the already-down equity: a fresh full daily loss on the same day. The anchor
is stored as ``(session_day, session_start_equity)`` per scope and reloaded
when the day still matches.
"""

from __future__ import annotations

from datetime import date

_DAY_KEY = "session_day"
_EQUITY_KEY = "session_start_equity"


class SessionMixin:
    """Mixed into ``Autopilot``; uses its engine, storage and scope."""

    _session: object | None
    _anchor_saved: object | None = None

    def _begin_session(self, day: date) -> None:
        """A new trading day for this runner: restore the stored anchor when it
        is today's, else let the next pass anchor afresh."""
        stored = self.storage.autopilot_values(self.scope)
        if stored.get(_DAY_KEY) == day.isoformat() and stored.get(_EQUITY_KEY):
            self.engine.reset_session(start_equity=float(stored[_EQUITY_KEY]))
            self._anchor_saved = day
        else:
            self.engine.reset_session()
        self._session = day

    def _save_session(self, day: date) -> None:
        """Persist the anchor once the engine has one for ``day``."""
        start = self.engine.session_start_equity
        if start is None or self._anchor_saved == day:
            return
        self.storage.set_autopilot_values(self.scope, {
            _DAY_KEY: day.isoformat(), _EQUITY_KEY: repr(float(start))})
        self._anchor_saved = day
