from datetime import date, datetime, timezone

import pandas as pd

from tradebot.arena.market import (
    ET,
    drop_incomplete_bars,
    is_market_open,
    next_open,
)


def _utc(y, m, d, h, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=timezone.utc)


def test_market_open_during_weekday_hours():
    # Wed 2024-01-03: 14:30 UTC == 09:30 ET (open), 14:00 == 09:00 (pre), 21:00 == 16:00 (closed)
    assert is_market_open(_utc(2024, 1, 3, 14, 30))
    assert not is_market_open(_utc(2024, 1, 3, 14, 0))
    assert not is_market_open(_utc(2024, 1, 3, 21, 0))


def test_weekend_and_holiday_are_closed():
    assert not is_market_open(_utc(2024, 1, 6, 15, 0))    # Saturday
    assert not is_market_open(_utc(2024, 1, 1, 15, 0))    # New Year's Day


def test_next_open_skips_weekend():
    # Fri 2024-01-05 22:00 UTC (after close) -> Mon 2024-01-08 09:30 ET
    nxt = next_open(_utc(2024, 1, 5, 22, 0)).astimezone(ET)
    assert nxt.date() == date(2024, 1, 8)
    assert (nxt.hour, nxt.minute) == (9, 30)


def _daily_df():
    idx = pd.to_datetime(["2024-01-02", "2024-01-03"], utc=True)
    return pd.DataFrame(
        {"open": [1, 2], "high": [1, 2], "low": [1, 2], "close": [1, 2], "volume": [1, 1]},
        index=idx,
    )


def test_drop_incomplete_daily_bar_before_close():
    df = _daily_df()
    # 2024-01-03 17:00 UTC == 12:00 ET, before the 16:00 ET close -> last bar incomplete.
    assert len(drop_incomplete_bars(df, "1day", _utc(2024, 1, 3, 17, 0))) == 1
    # After close -> the bar is complete and kept.
    assert len(drop_incomplete_bars(df, "1day", _utc(2024, 1, 3, 22, 0))) == 2
