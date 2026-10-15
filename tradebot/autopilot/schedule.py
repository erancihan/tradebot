"""When the autopilot passes next: on the poll inside market hours, else at
the next open. Pure functions of an injected ``now`` so the loop is testable
with a fake clock."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable
from zoneinfo import ZoneInfo

from ..market.us import ET

IsOpen = Callable[[datetime], bool]
NextOpen = Callable[[datetime], datetime]


def next_pass(now: datetime, poll_seconds: float, is_open: IsOpen,
              next_open: NextOpen) -> datetime:
    """The next poll if it still lands inside market hours, else the next open."""
    candidate = now + timedelta(seconds=poll_seconds)
    if is_open(candidate):
        return candidate
    return next_open(now)


def wait_seconds(now: datetime, next_at: datetime | None, poll_seconds: float) -> float:
    """How long the loop sleeps; never negative (a late wake passes at once)."""
    if next_at is None:
        return float(poll_seconds)
    return max(0.0, (next_at - now).total_seconds())


def session_day(now: datetime, tz: ZoneInfo = ET):
    """The exchange-local trading date: the daily-loss breaker's session."""
    return now.astimezone(tz).date()
