"""The exchange-calendar protocol, plus a table-driven implementation.

Everything that waits for a market (the autopilot loop, the season daemon,
the morning brief) asks a `MarketCalendar` instead of hard-coding New York
hours, so a second exchange is a new table rather than a new code path.
Every method takes its ``now`` or ``day`` as an argument, never reads a
clock, which keeps the callers testable with a fake clock.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Mapping, Protocol, runtime_checkable
from zoneinfo import ZoneInfo


@runtime_checkable
class MarketCalendar(Protocol):
    name: str
    timezone: ZoneInfo

    def is_open(self, now: datetime) -> bool: ...

    def next_open(self, now: datetime) -> datetime: ...

    def session(self, day: date) -> tuple[datetime, datetime] | None: ...

    def is_holiday(self, day: date) -> bool: ...


class TableCalendar:
    """A weekday session with a full-day holiday table and early closes.

    ``half_days`` maps a date to its early close time. A subclass sets the
    class attributes; nothing here is exchange-specific.
    """

    name: str = ""
    timezone: ZoneInfo
    open_time: time
    close_time: time
    holidays: frozenset[date] = frozenset()
    half_days: Mapping[date, time] = {}

    def is_holiday(self, day: date) -> bool:
        return day in self.holidays

    def session(self, day: date) -> tuple[datetime, datetime] | None:
        if day.weekday() >= 5 or self.is_holiday(day):
            return None
        close = self.half_days.get(day, self.close_time)
        return (datetime.combine(day, self.open_time, tzinfo=self.timezone),
                datetime.combine(day, close, tzinfo=self.timezone))

    def is_open(self, now: datetime) -> bool:
        local = now.astimezone(self.timezone)
        span = self.session(local.date())
        return span is not None and span[0] <= local < span[1]

    def next_open(self, now: datetime) -> datetime:
        """The next open strictly after ``now``, in ``now``'s timezone."""
        local = now.astimezone(self.timezone)
        day = local.date()
        for _ in range(21):   # the longest closure (a bridged holiday week) fits
            span = self.session(day)
            if span is not None and span[0] > local:
                return span[0].astimezone(now.tzinfo or self.timezone)
            day += timedelta(days=1)
        raise RuntimeError(f"no {self.name} open found within three weeks")
