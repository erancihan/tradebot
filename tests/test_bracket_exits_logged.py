"""Bracket exits reach the order log, so the offline account never keeps a
phantom long and History's trades see the stop.

Dry run: the engine books each simulated stop or target as an exit row.
Alpaca: the parent order's status carries its filled legs, and a reconcile
logs each one once.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from tradebot.broker import OrderStatus
from tradebot.broker.alpaca_broker import map_order_status
from tradebot.broker.base import LegFill
from tradebot.engine import fills, orders
from tradebot.models import Order, Side
from tradebot.portfolio_pnl import book, fills_from_orders
from tradebot.storage import Storage
from tradebot.web.repository.proposals import positions_from_orders

from .test_brackets import MovingBars, _broker, _engine, _flat
from .test_engine_fills import ScriptedBroker

T0 = datetime(2026, 10, 1, 15, 0, tzinfo=timezone.utc)


def _rows(st: Storage) -> list[dict]:
    cur = st._conn.execute("SELECT * FROM orders ORDER BY id")
    return [dict(zip([c[0] for c in cur.description], r)) for r in cur.fetchall()]


# --- dry run ------------------------------------------------------------------

def test_a_dry_run_stop_fill_lands_in_the_log_as_an_exit(tmp_path):
    db = str(tmp_path / "t.db")
    st = Storage(db)
    bars = MovingBars([_flat(100.0)])
    broker = _broker(bars)
    engine = _engine(bars, broker, stop_loss_pct=0.05)
    engine.storage = st
    engine.rebalance(now=T0)
    assert positions_from_orders(db, "dry_run") == {"SPY": 50.0}

    bars.push(open=99.0, high=99.0, low=90.0, close=92.0)
    orders.check_brackets(engine, now=T0 + timedelta(days=1))
    exit_row = _rows(st)[-1]
    assert exit_row["intent"] == "exit" and exit_row["side"] == "sell"
    assert exit_row["status"] == "filled"
    assert exit_row["filled_qty"] == 50.0 and exit_row["fill_price"] == pytest.approx(95.0)
    assert exit_row["filled_at"] == (T0 + timedelta(days=1)).isoformat()
    assert exit_row["broker_order_id"].startswith("bracket:dryrun-")
    assert positions_from_orders(db, "dry_run") == {}
    # A second look at the same bar fires nothing and logs nothing.
    orders.check_brackets(engine, now=T0 + timedelta(days=1))
    assert len(_rows(st)) == 2
    st.close()


def test_a_full_pass_books_the_stop_before_the_re_entry(tmp_path):
    db = str(tmp_path / "t.db")
    st = Storage(db)
    bars = MovingBars([_flat(100.0)])
    broker = _broker(bars)
    engine = _engine(bars, broker, stop_loss_pct=0.05)
    engine.storage = st
    engine.rebalance(now=T0)
    bars.push(open=99.0, high=99.0, low=90.0, close=92.0)
    engine.rebalance(now=T0 + timedelta(days=1))
    assert [(r["side"], r["intent"]) for r in _rows(st)] == [
        ("buy", "entry"), ("sell", "exit"), ("buy", "entry")]
    assert positions_from_orders(db, "dry_run") == {"SPY": broker.position("SPY").qty}
    trips, _, _ = book(fills_from_orders(st.filled_orders("dry_run")))
    assert [t.pnl for t in trips] == [pytest.approx(-250.0)]
    st.close()


def test_a_bracket_exit_is_logged_once_per_id(tmp_path):
    with Storage(tmp_path / "t.db") as st:
        leg = LegFill("bracket:x:1", "sell", 5.0, 95.0, T0)
        assert st.record_leg_fill("SPY", leg, "dry_run") is True
        assert st.record_leg_fill("SPY", leg, "dry_run") is False
        assert len(_rows(st)) == 1


# --- Alpaca: the parent's filled legs -----------------------------------------

def _log(st: Storage, oid: str, ts: datetime, side: Side, intent: str) -> None:
    st.record_order(Order("AAA", 10, side, created_at=ts), oid, "paper", price=100.0,
                    intent=intent)


def test_a_filled_leg_is_logged_once_and_the_trips_close(tmp_path):
    """Buy 10 @100, the stop sells @95, re-enter 10 @110, sell @120: -50, +100."""
    t_stop, t_in, t_out = T0 + timedelta(hours=1), T0 + timedelta(hours=2), T0 + timedelta(hours=3)
    with Storage(tmp_path / "t.db") as st:
        _log(st, "p1", T0, Side.BUY, "entry")
        _log(st, "p2", t_in, Side.BUY, "entry")
        _log(st, "s", t_out, Side.SELL, "exit")
        broker = ScriptedBroker({
            "p1": OrderStatus("filled", 10.0, 100.0, T0,
                              legs=(LegFill("leg1", "sell", 10.0, 95.0, t_stop),)),
            "p2": OrderStatus("filled", 10.0, 110.0, t_in),
            "s": OrderStatus("filled", 10.0, 120.0, t_out),
        })
        engine = SimpleNamespace(broker=broker, storage=st, mode="paper")
        fills.reconcile(engine, now=t_out)
        fills.reconcile(engine, now=t_out)
        legs = [r for r in _rows(st) if r["broker_order_id"] == "leg1"]
        assert len(legs) == 1
        assert legs[0]["intent"] == "exit" and legs[0]["side"] == "sell"
        assert legs[0]["filled_at"] == t_stop.isoformat()
        trips, still_open, unmatched = book(fills_from_orders(st.filled_orders("paper")))
        assert [t.pnl for t in trips] == [pytest.approx(-50.0), pytest.approx(100.0)]
        assert still_open == [] and unmatched == []


def test_a_parent_with_a_working_leg_is_asked_again_until_it_settles(tmp_path):
    with Storage(tmp_path / "t.db") as st:
        _log(st, "p1", T0, Side.BUY, "entry")
        broker = ScriptedBroker({"p1": OrderStatus("filled", 10.0, 100.0, T0, legs_open=True)})
        engine = SimpleNamespace(broker=broker, storage=st, mode="paper")
        fills.reconcile(engine, now=T0)
        fills.reconcile(engine, now=T0)
        assert broker.asked == ["p1", "p1"]           # filled, but its stop still rests
        broker.script["p1"] = OrderStatus(
            "filled", 10.0, 100.0, T0, legs=(LegFill("leg1", "sell", 10.0, 95.0, T0),))
        fills.reconcile(engine, now=T0)
        fills.reconcile(engine, now=T0)
        assert broker.asked == ["p1"] * 3              # settled: not asked again
        assert [r["broker_order_id"] for r in _rows(st)] == ["p1", "leg1"]


def _sdk(status, qty, price, at, legs=None, side="buy", oid="x"):
    return SimpleNamespace(id=oid, status=SimpleNamespace(value=status), filled_qty=qty,
                           filled_avg_price=price, filled_at=at,
                           side=SimpleNamespace(value=side), legs=legs)


def test_alpaca_maps_filled_legs_and_whether_one_still_works():
    stop = _sdk("filled", "10", "95.0", T0, side="sell", oid="leg-stop")
    target = _sdk("canceled", "0", None, None, side="sell", oid="leg-target")
    status = map_order_status(_sdk("filled", "10", "100", T0, legs=[stop, target]))
    assert status.legs == (LegFill("leg-stop", "sell", 10.0, 95.0, T0),)
    assert status.legs_open is False
    resting = map_order_status(_sdk("filled", "10", "100", T0,
                                    legs=[_sdk("new", "0", None, None, side="sell")]))
    assert resting.legs == () and resting.legs_open is True
    assert map_order_status(_sdk("filled", "10", "100", T0)).legs == ()
