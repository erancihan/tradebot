"""Calendar names as they appear in the config's ``market:`` key."""

from __future__ import annotations

from .base import MarketCalendar
from .bist import BorsaIstanbul
from .us import USEquities

CALENDARS: dict[str, type] = {"us_equities": USEquities, "bist": BorsaIstanbul}


def check_market(name: str) -> str:
    """The name itself, or a ValueError listing the known calendars."""
    if name not in CALENDARS:
        raise ValueError(f"market must be one of {sorted(CALENDARS)}, got {name!r}")
    return name


def get_calendar(name: str) -> MarketCalendar:
    return CALENDARS[check_market(name)]()
