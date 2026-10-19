"""Offline positions from the order log never go short on an exit."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tradebot.models import Order, Side
from tradebot.storage import Storage
from tradebot.web.repository.proposals import positions_from_orders

T0 = datetime(2026, 10, 1, 15, 0, tzinfo=timezone.utc)


def _log(st, symbol, qty, side, intent, minutes):
    st.record_order(Order(symbol, qty, side, created_at=T0 + timedelta(minutes=minutes)),
                    f"o{minutes}", "paper", price=10.0, intent=intent)


def test_an_exit_with_no_recorded_buy_reads_flat(tmp_path):
    """XYZ was bought by hand; the unlisted rule sold it to flat."""
    db = str(tmp_path / "t.db")
    with Storage(db) as st:
        _log(st, "XYZ", 10, Side.SELL, "exit", 0)
    assert positions_from_orders(db, "paper") == {}


def test_an_exit_larger_than_the_holding_stops_at_zero(tmp_path):
    db = str(tmp_path / "t.db")
    with Storage(db) as st:
        _log(st, "AAA", 4, Side.BUY, "entry", 0)
        _log(st, "AAA", 10, Side.SELL, "exit", 1)
        _log(st, "AAA", 3, Side.BUY, "entry", 2)
    assert positions_from_orders(db, "paper") == {"AAA": 3.0}


def test_a_genuine_partial_sell_still_reads_the_rest(tmp_path):
    db = str(tmp_path / "t.db")
    with Storage(db) as st:
        _log(st, "AAA", 10, Side.BUY, "entry", 0)
        _log(st, "AAA", 4, Side.SELL, "exit", 1)
    assert positions_from_orders(db, "paper") == {"AAA": 6.0}


def test_an_entry_sell_still_opens_a_short(tmp_path):
    db = str(tmp_path / "t.db")
    with Storage(db) as st:
        _log(st, "AAA", 5, Side.SELL, "entry", 0)
    assert positions_from_orders(db, "paper") == {"AAA": -5.0}
