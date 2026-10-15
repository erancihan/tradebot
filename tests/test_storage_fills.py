"""``filled_orders``: the order-log rows History builds round trips from."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from tradebot.broker import OrderStatus
from tradebot.models import Order, Side
from tradebot.storage import Storage
from tradebot.web.repository import TradingRepository

from .test_storage import _OLD_ORDERS

T0 = datetime(2026, 10, 15, 14, 30, tzinfo=timezone.utc)


def _log(st: Storage, symbol: str, qty: float, ts: datetime, status: OrderStatus | None,
         side: Side = Side.BUY, mode: str = "paper") -> None:
    st.record_order(Order(symbol=symbol, qty=qty, side=side, created_at=ts),
                    f"b-{symbol}-{ts.isoformat()}", mode, price=100.0)
    oid = st._conn.execute("SELECT max(id) FROM orders").fetchone()[0]
    if status is not None:
        st.set_order_fill(oid, status)


def _seed(path) -> None:
    with Storage(path) as st:
        later = T0 + timedelta(days=1)
        # Submitted first, filled last: fill order wins over submit order.
        _log(st, "LATE", 1, T0, OrderStatus("filled", 1, 10.0, later + timedelta(hours=2)))
        _log(st, "SPY", 10, T0 + timedelta(hours=1),
             OrderStatus("filled", 10, 101.0, T0 + timedelta(hours=1)))
        _log(st, "PART", 10, T0 + timedelta(hours=2),
             OrderStatus("partially_filled", 4, 50.0, later))
        _log(st, "CXP", 10, T0 + timedelta(hours=3),
             OrderStatus("canceled", 3, 20.0, later + timedelta(hours=1)))
        _log(st, "NEW", 5, T0, None)                                       # never asked
        _log(st, "WORK", 5, T0, OrderStatus("new", 0, None, None))         # working
        _log(st, "GONE", 5, T0, OrderStatus("canceled", 0, None, None))    # nothing filled
        _log(st, "DRY", 5, T0, OrderStatus("filled", 5, 1.0, T0), mode="dry_run")


EXPECTED = [("SPY", 10.0, 101.0), ("PART", 4.0, 50.0), ("CXP", 3.0, 20.0), ("LATE", 1.0, 10.0)]


def test_filled_orders_are_the_known_fills_of_one_account_in_fill_order(tmp_path):
    _seed(tmp_path / "t.db")
    with Storage(tmp_path / "t.db") as st:
        rows = st.filled_orders("paper")
    assert [(r["symbol"], r["filled_qty"], r["fill_price"]) for r in rows] == EXPECTED
    with Storage(tmp_path / "t.db") as st:
        assert [r["symbol"] for r in st.filled_orders("dry_run")] == ["DRY"]


def test_the_web_repository_reads_the_same_rows(tmp_path):
    _seed(tmp_path / "t.db")
    rows = TradingRepository(str(tmp_path / "t.db")).filled_orders("paper")
    assert [(r["symbol"], r["filled_qty"], r["fill_price"]) for r in rows] == EXPECTED


def test_a_log_from_before_the_fill_columns_has_no_fills(tmp_path):
    con = sqlite3.connect(tmp_path / "old.db")
    con.execute(_OLD_ORDERS)
    con.commit()
    con.close()
    assert TradingRepository(str(tmp_path / "old.db")).filled_orders("paper") == []
    assert TradingRepository(str(tmp_path / "missing.db")).filled_orders("paper") == []
