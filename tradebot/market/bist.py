"""Borsa Istanbul (BIST) equity market: 10:00-18:00 Europe/Istanbul.

Scheduling only: there is no BIST broker adapter yet, so a ``market: bist``
config moves when the autopilot and the brief wake, never where orders go.

The holiday table covers 2026 and 2027 and EXPIRES at the end of 2027.
Sources: the Turkish official holiday law (Law 2429) for the fixed dates, and
the Diyanet calendar for the religious ones. Ramadan Feast and the Feast of
the Sacrifice follow the lunar calendar and move about eleven days earlier
every year, so they cannot be computed by rule; the government also
announces bridge days ("idari izin") at short notice, and Borsa Istanbul
publishes its own closure list each year. Check that list before relying on
a date here, and extend the table before 2028 (the test fails a year ahead).
"""

from __future__ import annotations

from datetime import date, time
from zoneinfo import ZoneInfo

from .base import TableCalendar

IST = ZoneInfo("Europe/Istanbul")

#: Last calendar year the holiday table covers.
HOLIDAY_TABLE_THROUGH = 2027

#: A half day (the eve of Republic Day and of each feast) trades the morning
#: only. BIST's actual half-day close is around 12:30; 13:00 is the
#: conservative bound the scheduler needs (it only asks "is it open?").
HALF_DAY_CLOSE = time(13, 0)

_FIXED = [(1, 1), (4, 23), (5, 1), (5, 19), (7, 15), (8, 30), (10, 29)]

# Ramadan Feast (Ramazan Bayrami) and Feast of the Sacrifice (Kurban Bayrami).
_RELIGIOUS = [
    date(2026, 3, 20), date(2026, 3, 21), date(2026, 3, 22),
    date(2026, 5, 27), date(2026, 5, 28), date(2026, 5, 29), date(2026, 5, 30),
    date(2027, 3, 9), date(2027, 3, 10), date(2027, 3, 11),
    date(2027, 5, 16), date(2027, 5, 17), date(2027, 5, 18), date(2027, 5, 19),
]

#: Feast eves ("arife") and the eve of Republic Day.
_EVES = [date(2026, 3, 19), date(2026, 5, 26), date(2026, 10, 28),
         date(2027, 3, 8), date(2027, 5, 15), date(2027, 10, 28)]

BIST_HOLIDAYS: frozenset[date] = frozenset(
    [date(y, m, d) for y in (2026, 2027) for m, d in _FIXED] + _RELIGIOUS)


class BorsaIstanbul(TableCalendar):
    name = "bist"
    timezone = IST
    open_time = time(10, 0)
    close_time = time(18, 0)
    holidays = BIST_HOLIDAYS
    half_days = {d: HALF_DAY_CLOSE for d in _EVES}
