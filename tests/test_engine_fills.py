"""Fills: the broker reports what became of an order, and the log keeps it.

Offline throughout: a scripted fake broker, the dry-run broker, and a stub
object standing in for an Alpaca SDK order.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from tradebot.broker import DryRunBroker, OrderStatus
from tradebot.broker.alpaca_broker import map_order_status
from tradebot.engine import fills
from tradebot.models import Order, Side
from tradebot.storage import Storage
from tradebot.storage.orders import effective_qty

from .test_autopilot import OPEN_NOW, SYMBOLS, build
from .test_dryrun import StubData
from .test_storage import _OLD_ORDERS

NOW = datetime(2026, 10, 15, 15, 0, tzinfo=timezone.utc)
FILLED = OrderStatus("filled", 13.0, 767.24, NOW)


class ScriptedBroker:
    """Answers `order_status` from a script: a status, None, or an exception."""

    def __init__(self, script: dict) -> None:
        self.script, self.asked = script, []

    def order_status(self, broker_order_id: str):
        self.asked.append(broker_order_id)
        answer = self.script.get(broker_order_id)
        if isinstance(answer, Exception):
            raise answer
        return answer


def _log(st: Storage, oid: str | None, ts: datetime = NOW, qty: float = 13,
         side: Side = Side.BUY, mode: str = "paper", symbol: str = "SPY") -> int:
    st.record_order(Order(symbol=symbol, qty=qty, side=side, created_at=ts), oid, mode,
                    price=766.85)
    return st._conn.execute("SELECT max(id) FROM orders").fetchone()[0]


def _row(st: Storage, order_id: int) -> dict:
    cur = st._conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,))
    return dict(zip([c[0] for c in cur.description], cur.fetchone()))


# --- the broker side ----------------------------------------------------------

def test_order_status_terminal_states():
    assert FILLED.is_terminal
    assert OrderStatus("rejected", 0.0, None, None).is_terminal
    assert not OrderStatus("partially_filled", 5.0, 1.0, None).is_terminal
    assert not OrderStatus("new", 0.0, None, None).is_terminal


def test_dry_run_order_status_is_the_simulated_fill():
    broker = DryRunBroker(StubData({"SPY": 100.0}), initial_cash=10_000, slippage_bps=10)
    oid = broker.submit(Order("SPY", 10, Side.BUY, created_at=NOW))
    status = broker.order_status(oid)
    assert status == OrderStatus("filled", 10.0, pytest.approx(100.1), NOW)
    assert broker.order_status("dryrun-99") is None


def test_a_broker_that_cannot_report_says_none():
    from tradebot.broker import Broker

    class Mute(Broker):
        account = positions = position = is_market_open = submit = cancel_all = None

    Mute.__abstractmethods__ = frozenset()
    assert Mute().order_status("x") is None


@pytest.mark.parametrize("raw, qty, price, expected", [
    ("filled", "13", "767.24", OrderStatus("filled", 13.0, 767.24, NOW)),
    ("partially_filled", "5", "767.0", OrderStatus("partially_filled", 5.0, 767.0, NOW)),
    ("pending_new", "0", None, OrderStatus("new", 0.0, None, NOW)),
    ("canceled", "0", None, OrderStatus("canceled", 0.0, None, NOW)),
    ("done_for_day", "0", None, OrderStatus("unknown", 0.0, None, NOW)),
])
def test_alpaca_orders_map_onto_our_status(raw, qty, price, expected):
    sdk_order = SimpleNamespace(status=SimpleNamespace(value=raw), filled_qty=qty,
                                filled_avg_price=price, filled_at=NOW)
    assert map_order_status(sdk_order) == expected


# --- the order log ------------------------------------------------------------

def test_an_old_order_log_gains_the_fill_columns_on_open(tmp_path):
    db = str(tmp_path / "old.db")
    con = sqlite3.connect(db)
    con.execute(_OLD_ORDERS)
    con.commit()
    con.close()
    with Storage(db) as st:
        cols = {r[1] for r in st._conn.execute("PRAGMA table_info(orders)")}
    assert {"price", "status", "filled_qty", "fill_price", "filled_at"} <= cols


def test_open_orders_are_recent_unsettled_and_known_to_the_broker(tmp_path):
    with Storage(tmp_path / "t.db") as st:
        fresh = _log(st, "a")
        _log(st, None)                                         # never reached a broker
        _log(st, "old", ts=NOW - timedelta(days=10))
        _log(st, "other", mode="dry_run")
        done = _log(st, "done")
        st.set_order_fill(done, FILLED)
        working = _log(st, "working")
        st.set_order_fill(working, OrderStatus("partially_filled", 5.0, 767.0, None))
        since = (NOW - timedelta(days=7)).isoformat()
        assert [r["id"] for r in st.open_orders("paper", since)] == [fresh, working]
        assert _row(st, done)["fill_price"] == 767.24
        assert _row(st, done)["filled_at"] == NOW.isoformat()


@pytest.mark.parametrize("row, expected", [
    ({"qty": 13, "status": None, "filled_qty": None}, 13.0),
    ({"qty": 13, "status": "new", "filled_qty": 0.0}, 13.0),
    ({"qty": 13, "status": "filled", "filled_qty": 13.0}, 13.0),
    ({"qty": 13, "status": "partially_filled", "filled_qty": 5.0}, 5.0),
    ({"qty": 13, "status": "canceled", "filled_qty": 0.0}, 0.0),
    ({"qty": 13, "status": "canceled", "filled_qty": 4.0}, 4.0),
    ({"qty": 13, "status": "rejected", "filled_qty": None}, 0.0),
    ({"qty": 13}, 13.0),                                         # an unmigrated row
])
def test_effective_qty_counts_what_filled(row, expected):
    assert effective_qty(row) == expected


# --- reconcile ----------------------------------------------------------------

def test_reconcile_writes_fills_and_counts_the_changed_rows(tmp_path):
    with Storage(tmp_path / "t.db") as st:
        a, b = _log(st, "a"), _log(st, "b")
        c = _log(st, "c")
        old = _log(st, "old", ts=NOW - timedelta(days=8))
        engine = SimpleNamespace(broker=ScriptedBroker({
            "a": FILLED, "b": RuntimeError("boom"), "c": None, "old": FILLED,
        }), storage=st, mode="paper")
        assert fills.reconcile(engine, now=NOW) == 1
        assert engine.broker.asked == ["a", "b", "c"]         # `old` is past the lookback
        assert _row(st, a)["status"] == "filled" and _row(st, a)["filled_qty"] == 13.0
        assert _row(st, b)["status"] is None and _row(st, c)["status"] is None
        assert _row(st, old)["status"] is None
        # `a` is terminal now: never asked again. An unchanged answer is no change.
        engine.broker.script["b"] = OrderStatus("new", 0.0, None, None)
        assert fills.reconcile(engine, now=NOW) == 1
        assert fills.reconcile(engine, now=NOW) == 0
        assert engine.broker.asked.count("a") == 1


def test_reconcile_without_storage_does_nothing():
    engine = SimpleNamespace(broker=ScriptedBroker({}), storage=None, mode="paper")
    assert fills.reconcile(engine, now=NOW) == 0


def test_an_approval_records_the_fill_at_once(tmp_path):
    pilot, broker, _, _ = build(tmp_path)
    engine, storage = pilot.engine, pilot.storage
    engine.step(submit=False, now=OPEN_NOW)
    ids = [ln["id"] for ln in storage.pending_lines("dry_run")]
    engine.submit_lines(ids, now=OPEN_NOW)
    rows = storage._conn.execute(
        "SELECT broker_order_id, status, filled_qty, qty, fill_price FROM orders").fetchall()
    assert len(rows) == len(SYMBOLS)
    for oid, status, filled, qty, fill_price in rows:
        assert status == "filled" and filled == qty
        assert fill_price == broker.order_status(oid).fill_price


def test_an_automatic_pass_records_its_fills_too(tmp_path):
    pilot, _, _, _ = build(tmp_path)
    pilot.engine.step(submit=True, now=OPEN_NOW)
    statuses = pilot.storage._conn.execute("SELECT status FROM orders").fetchall()
    assert [tuple(r) for r in statuses] == [("filled",)] * len(SYMBOLS)


# --- the autopilot ------------------------------------------------------------

def test_an_autopilot_pass_reconciles_before_it_steps(tmp_path, monkeypatch):
    pilot, broker, _, _ = build(tmp_path)
    calls: list[str] = []
    real_reconcile, real_step = fills.reconcile, pilot.engine.step
    monkeypatch.setattr(fills, "reconcile",
                        lambda engine, **kw: calls.append("reconcile") or real_reconcile(engine, **kw))
    monkeypatch.setattr(pilot.engine, "step",
                        lambda **kw: calls.append("step") or real_step(**kw))
    pilot.set_mode("auto")
    pilot.tick()
    assert calls[:2] == ["reconcile", "step"]


def test_a_failing_reconcile_never_fails_the_pass(tmp_path, monkeypatch):
    pilot, broker, _, _ = build(tmp_path)

    def boom(engine, **kw):
        raise RuntimeError("broker down")

    monkeypatch.setattr(fills, "reconcile", boom)
    pilot.set_mode("auto")
    state = pilot.tick()
    assert state.last_error is None and broker._order_seq == len(SYMBOLS)


# --- the Today refresh --------------------------------------------------------

def test_the_today_refresh_syncs_paper_fills_only(tmp_path):
    from tradebot.web.services import advisor_service

    db = str(tmp_path / "t.db")
    with Storage(db) as st:
        paper, dry = _log(st, "p"), _log(st, "d", mode="dry_run")
    broker = ScriptedBroker({"p": FILLED, "d": FILLED})
    assert advisor_service.sync_fills(broker, db, now=NOW) == 1
    assert broker.asked == ["p"]
    with Storage(db) as st:
        assert _row(st, paper)["status"] == "filled" and _row(st, dry)["status"] is None


def test_the_today_sync_lookback_runs_from_the_given_now(tmp_path, monkeypatch):
    """A fixed `now` pins the 7-day lookback: the wall clock a month later
    must not age the order out (the test used to fail after 2026-10-22)."""
    from tradebot.web.services import advisor_service

    monkeypatch.setattr(fills, "utcnow", lambda: NOW + timedelta(days=30))
    db = str(tmp_path / "t.db")
    with Storage(db) as st:
        paper = _log(st, "p")
    assert advisor_service.sync_fills(ScriptedBroker({"p": FILLED}), db, now=NOW) == 1
    with Storage(db) as st:
        assert _row(st, paper)["status"] == "filled"


# --- ids across processes -----------------------------------------------------

def test_a_second_dry_run_broker_never_claims_an_earlier_ones_order(tmp_path):
    """A dry-run account dies with its process, but the log does not: a new
    broker's first order must not share an id with an old logged one."""
    first = DryRunBroker(StubData({"SPY": 100.0}), initial_cash=10_000)
    second = DryRunBroker(StubData({"SPY": 50.0}), initial_cash=10_000)
    old_id = first.submit(Order("SPY", 3, Side.BUY, created_at=NOW))
    second.submit(Order("SPY", 40, Side.BUY, created_at=NOW))
    with Storage(tmp_path / "t.db") as st:
        row_id = _log(st, old_id, qty=3, mode="dry_run")
        engine = SimpleNamespace(broker=second, storage=st, mode="dry_run")
        assert fills.reconcile(engine, now=NOW) == 0
        assert _row(st, row_id)["status"] is None


def test_reconcile_refuses_a_fill_larger_than_the_order(tmp_path, caplog):
    with Storage(tmp_path / "t.db") as st:
        row_id = _log(st, "x", qty=3)
        engine = SimpleNamespace(broker=ScriptedBroker({"x": FILLED}), storage=st,
                                 mode="paper")
        with caplog.at_level("WARNING", logger="tradebot.fills"):
            assert fills.reconcile(engine, now=NOW) == 0
        assert _row(st, row_id)["status"] is None
        assert "13.0 filled of 3.0 ordered" in caplog.text
