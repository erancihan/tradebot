"""Exchange calendars: the US calendar is the old helpers behind a protocol,
and BIST is a table-driven second exchange."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import pytest

from tradebot.arena import market as old
from tradebot.market import BorsaIstanbul, MarketCalendar, USEquities, get_calendar
from tradebot.market.bist import HOLIDAY_TABLE_THROUGH, IST


def _utc(y, m, d, h, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=timezone.utc)


# Weekdays, a weekend, NYSE holidays (Good Friday 2026, July 3 2026 observed)
# and both sides of the 2026 US DST switch (Sunday March 8).
SAMPLES = [
    _utc(2026, 3, 6, 13, 45), _utc(2026, 3, 6, 14, 45),      # Fri, EST: pre / open
    _utc(2026, 3, 7, 12, 0),                                   # Saturday
    _utc(2026, 3, 9, 13, 45), _utc(2026, 3, 9, 20, 30),      # Mon, EDT: open / closed
    _utc(2026, 4, 3, 15, 0), _utc(2026, 7, 3, 15, 0),        # holidays
    _utc(2026, 10, 14, 15, 0), _utc(2026, 12, 24, 21, 5),
    _utc(2027, 11, 24, 23, 0),
]


@pytest.mark.parametrize("now", SAMPLES)
def test_us_calendar_matches_the_old_arena_market_helpers(now):
    us = USEquities()
    assert us.is_open(now) == old.is_market_open(now)
    assert us.next_open(now) == old.next_open(now)
    assert us.is_holiday(now.date()) == (now.date() in old.DEFAULT_HOLIDAYS)
    span = us.session(now.astimezone(old.ET).date())
    assert (span is not None) == old.is_trading_day(now.astimezone(old.ET).date())


def test_us_calendar_pins_the_dst_switch_and_a_holiday():
    us = USEquities()
    assert not us.is_open(_utc(2026, 3, 6, 13, 45))           # 08:45 EST
    assert us.is_open(_utc(2026, 3, 9, 13, 45))               # 09:45 EDT
    assert us.next_open(_utc(2026, 3, 7, 12, 0)) == _utc(2026, 3, 9, 13, 30)
    assert us.is_holiday(date(2026, 4, 3)) and us.session(date(2026, 4, 3)) is None
    assert us.next_open(_utc(2026, 4, 2, 21, 0)) == _utc(2026, 4, 6, 13, 30)


def test_bist_session_hours_and_a_holiday():
    bist = get_calendar("bist")
    assert isinstance(bist, BorsaIstanbul) and isinstance(bist, MarketCalendar)
    # Istanbul is UTC+3 all year: 10:00 local is 07:00 UTC.
    assert not bist.is_open(_utc(2026, 10, 14, 6, 59))
    assert bist.is_open(_utc(2026, 10, 14, 7, 0))
    assert not bist.is_open(_utc(2026, 10, 14, 15, 0))       # 18:00 local: closed
    assert bist.session(date(2026, 10, 14)) == (
        datetime(2026, 10, 14, 10, 0, tzinfo=IST), datetime(2026, 10, 14, 18, 0, tzinfo=IST))
    # Republic Day (Thu Oct 29) is closed; the eve closes at 13:00.
    assert bist.is_holiday(date(2026, 10, 29)) and bist.session(date(2026, 10, 29)) is None
    assert bist.session(date(2026, 10, 28))[1].time() == time(13, 0)
    assert not bist.is_open(_utc(2026, 10, 28, 10, 30))      # 13:30 local
    assert bist.next_open(_utc(2026, 10, 28, 12, 0)) == _utc(2026, 10, 30, 7, 0)


def test_bist_skips_the_whole_feast_of_the_sacrifice():
    bist = get_calendar("bist")
    # Eve Tue 2026-05-26 trades the morning; Wed-Sat is the feast.
    assert bist.next_open(_utc(2026, 5, 26, 12, 0)) == _utc(2026, 6, 1, 7, 0)


def test_bist_holiday_table_has_not_run_out():
    """Deliberately time-dependent: fail a year before the table expires."""
    this_year = datetime.now(timezone.utc).year
    assert HOLIDAY_TABLE_THROUGH >= this_year + 1, (
        "extend BIST_HOLIDAYS: the lunar feasts move every year")


def test_unknown_calendar_name_raises():
    with pytest.raises(ValueError, match="us_equities"):
        get_calendar("nasdaq_tokyo")


def test_us_next_open_is_returned_in_the_callers_timezone():
    now = datetime(2026, 10, 17, 15, 0, tzinfo=IST)
    nxt = get_calendar("us_equities").next_open(now)
    assert nxt.tzinfo == IST and nxt - now > timedelta(0)
