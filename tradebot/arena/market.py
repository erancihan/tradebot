"""US-equity market-hours helpers for the season daemon.

Pure functions (a ``now`` is always passed in, never read), so they're fully
testable offline. The holiday set is a pragmatic approximation of NYSE full-day
closures — extend it or pass your own ``holidays``; for production accuracy a
real market-calendar library is the right move (noted in CLAUDE.md).
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

ET = ZoneInfo("America/New_York")
MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)

# NYSE full-day holidays, 2024–2026 (approximate; early closes not modelled).
DEFAULT_HOLIDAYS: frozenset[date] = frozenset({
    date(2024, 1, 1), date(2024, 1, 15), date(2024, 2, 19), date(2024, 3, 29),
    date(2024, 5, 27), date(2024, 6, 19), date(2024, 7, 4), date(2024, 9, 2),
    date(2024, 11, 28), date(2024, 12, 25),
    date(2025, 1, 1), date(2025, 1, 20), date(2025, 2, 17), date(2025, 4, 18),
    date(2025, 5, 26), date(2025, 6, 19), date(2025, 7, 4), date(2025, 9, 1),
    date(2025, 11, 27), date(2025, 12, 25),
    date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16), date(2026, 4, 3),
    date(2026, 5, 25), date(2026, 6, 19), date(2026, 7, 3), date(2026, 9, 7),
    date(2026, 11, 26), date(2026, 12, 25),
})

_TF_DURATION = {
    "1min": timedelta(minutes=1),
    "5min": timedelta(minutes=5),
    "15min": timedelta(minutes=15),
    "1hour": timedelta(hours=1),
}


def is_trading_day(day: date, holidays=DEFAULT_HOLIDAYS) -> bool:
    return day.weekday() < 5 and day not in holidays


def is_market_open(now: datetime, holidays=DEFAULT_HOLIDAYS) -> bool:
    et = now.astimezone(ET)
    if not is_trading_day(et.date(), holidays):
        return False
    return MARKET_OPEN <= et.time() < MARKET_CLOSE


def next_open(now: datetime, holidays=DEFAULT_HOLIDAYS) -> datetime:
    """The next market open strictly after ``now`` (returned in ``now``'s tz)."""
    et = now.astimezone(ET)
    day = et.date()
    for _ in range(14):  # at most ~2 weeks of closures
        if is_trading_day(day, holidays):
            candidate = datetime.combine(day, MARKET_OPEN, tzinfo=ET)
            if candidate > et:
                return candidate.astimezone(now.tzinfo or ET)
        day += timedelta(days=1)
    raise RuntimeError("no market open found within two weeks")


def bar_is_complete(ts, timeframe: str, now: datetime) -> bool:
    """Whether the bar at ``ts`` represents a fully-closed period as of ``now``."""
    ts = pd.Timestamp(ts)
    if timeframe == "1day":
        # Daily bars are labelled by session date; use that date directly (an ET
        # conversion of a midnight-UTC stamp would land on the previous day).
        close_dt = datetime.combine(ts.date(), MARKET_CLOSE, tzinfo=ET)
        return now.astimezone(ET) >= close_dt
    ts = ts.to_pydatetime()
    duration = _TF_DURATION.get(timeframe)
    if duration is None:
        return True
    return now >= ts + duration


def drop_incomplete_bars(df, timeframe: str, now: datetime):
    """Drop a trailing still-forming bar (e.g. today's daily bar before close)."""
    if df is None or len(df) == 0:
        return df
    if not bar_is_complete(df.index[-1], timeframe, now):
        return df.iloc[:-1]
    return df
