"""Morning brief: the day's proposal, sent a set time before the open.

The brief is a read-only preview. It asks the engine's ``propose`` (the
advisor, the same lines the Today page shows) and never stores pending lines
or submits anything, so it runs in every mode, off included. It is sent once
per session: the open it was sent for is stored with the autopilot state, so
a restarted loop does not send the same morning twice.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from ..market import MarketCalendar

log = logging.getLogger("tradebot.autopilot")

_SENT_KEY = "brief_for"


class MorningBrief:
    """When the brief is due: ``minutes`` before each open of ``calendar``."""

    def __init__(self, minutes: int, calendar: MarketCalendar) -> None:
        if minutes <= 0:
            raise ValueError(f"brief_minutes_before_open must be positive, got {minutes}")
        self.lead = timedelta(minutes=minutes)
        self.calendar = calendar

    def target_open(self, now: datetime, sent_for: datetime | None) -> datetime:
        """The open the next brief is for: the coming open, or the one after
        it once the coming open's brief has gone out."""
        opens = self.calendar.next_open(now)
        if sent_for is not None and opens <= sent_for:
            opens = self.calendar.next_open(opens)
        return opens

    def due_at(self, now: datetime, sent_for: datetime | None) -> datetime:
        return self.target_open(now, sent_for) - self.lead


def _qty(value: float) -> str:
    """3 not 3.0; fractional shares keep up to four decimals."""
    q = abs(float(value))
    return str(int(q)) if q.is_integer() else f"{q:.4f}".rstrip("0").rstrip(".")


def line_text(line) -> str:
    """One plain line per symbol: ``BUY 3 SPY (reason)``."""
    if line.skipped:
        return f"SKIP {line.symbol} ({line.reason})"
    if line.action == "hold" or not line.order_qty:
        return f"HOLD {line.symbol} ({line.reason})"
    return f"{line.action.upper()} {_qty(line.order_qty)} {line.symbol} ({line.reason})"


def compose(engine, opens_at: datetime, now: datetime) -> dict:
    """The brief event for one open, from a dry proposal (nothing stored)."""
    acct = engine.broker.account()
    proposal = engine.propose(acct.equity, acct.cash, now=now)
    return {
        "type": "brief", "opens_at": opens_at.isoformat(),
        "text": "\n".join(line_text(ln) for ln in proposal.lines),
        "lines": [{"symbol": ln.symbol, "action": ln.action, "qty": abs(ln.order_qty),
                   "reason": ln.reason, "skipped": ln.skipped} for ln in proposal.lines],
    }


class BriefMixin:
    """Mixed into ``Autopilot``; uses its engine, storage, clock and notifier."""

    brief: MorningBrief | None

    def _brief_sent_for(self) -> datetime | None:
        raw = self.storage.autopilot_values(self.scope).get(_SENT_KEY)
        return datetime.fromisoformat(raw) if raw else None

    def _maybe_brief(self, now: datetime) -> None:
        """Send the brief when its time has come and it has not gone out."""
        if self.brief is None:
            return
        sent_for = self._brief_sent_for()
        if self.brief.due_at(now, sent_for) > now:
            return
        opens_at = self.brief.target_open(now, sent_for)
        # Marked before composing: a brief that fails is logged and skipped,
        # not retried on every wake until the open.
        self._set(**{_SENT_KEY: opens_at})
        try:
            event = compose(self.engine, opens_at, now)
        except Exception:  # noqa: BLE001 - a preview never breaks the loop
            log.exception("Morning brief failed for the %s open", opens_at)
            return
        self._notify(event)

    def _brief_wake(self, now: datetime) -> datetime | None:
        return None if self.brief is None else self.brief.due_at(now, self._brief_sent_for())
