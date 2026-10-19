"""A dry-run account dies with its process: History shows the newest run only.

Each dry-run broker (web autopilot build, `tradebot run --dry-run`) records an
account start; History's dry_run reads begin there. Paper never records one.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tradebot.broker import OrderStatus
from tradebot.config import Settings
from tradebot.models import Order, Side
from tradebot.storage import Storage
from tradebot.web.repository import TradingRepository
from tradebot.web.services import autopilot_build, history_service, history_trades

T0 = datetime(2026, 10, 1, 15, 0, tzinfo=timezone.utc)


def _fill(st, mode, side, qty, price, minutes, intent):
    at = T0 + timedelta(minutes=minutes)
    st.record_order(Order("AAA", qty, side, created_at=at), f"{mode}-{minutes}", mode,
                    price=price, intent=intent)
    row_id = st._conn.execute("SELECT max(id) FROM orders").fetchone()[0]
    st.set_order_fill(row_id, OrderStatus("filled", float(qty), price, at))


def _scenario(db: str) -> None:
    with Storage(db) as st:
        st.record_account_start("dry_run")                 # process 1
        st.record_equity(10_000, 10_000, "dry_run")
        _fill(st, "dry_run", Side.BUY, 10, 100.0, 0, "entry")
        _fill(st, "paper", Side.BUY, 5, 50.0, 1, "entry")
        st.record_equity(5_000, 4_750, "paper")
        st.record_equity(10_050, 9_000, "dry_run")
        st.record_account_start("dry_run")                 # restart: a fresh account
        st.record_equity(10_000, 10_000, "dry_run")
        _fill(st, "dry_run", Side.BUY, 10, 110.0, 10, "entry")
        _fill(st, "dry_run", Side.SELL, 10, 120.0, 20, "exit")
        _fill(st, "paper", Side.SELL, 5, 60.0, 21, "exit")
        st.record_equity(10_100, 10_100, "dry_run")


def test_dry_run_history_starts_at_the_newest_run(tmp_path):
    db = str(tmp_path / "t.db")
    _scenario(db)
    repo = TradingRepository(db)
    trades = history_trades.view(repo, "dry_run")
    assert [t["pnl"] for t in trades["trades"]] == [pytest.approx(100.0)]
    assert trades["open"] == [] and trades["unmatched"] == []
    perf = history_service.performance(repo, "dry_run")
    assert perf["points"] == 2 and perf["start"] == 10_000 and perf["now"] == 10_100
    curve = repo.equity_series(mode="dry_run")
    assert [r["equity"] for r in curve] == [10_000, 10_100]
    page = history_service.events_page(repo, "dry_run")
    assert [e["ts"][:16] for e in page["events"]] == ["2026-10-01T15:20", "2026-10-01T15:10"]
    start = repo.account_start("dry_run")
    assert start is not None and start["ts"]


def test_paper_history_is_untouched(tmp_path):
    db = str(tmp_path / "t.db")
    _scenario(db)
    repo = TradingRepository(db)
    assert repo.account_start("paper") is None
    trades = history_trades.view(repo, "paper")
    assert [t["pnl"] for t in trades["trades"]] == [pytest.approx(50.0)]
    assert len(history_service.events_page(repo, "paper")["events"]) == 2


def test_a_log_without_the_table_reads_as_no_start(tmp_path):
    import sqlite3

    db = str(tmp_path / "old.db")
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE equity_snapshots (id INTEGER PRIMARY KEY, ts TEXT, equity REAL,"
                " cash REAL, mode TEXT)")
    con.execute("INSERT INTO equity_snapshots (ts, equity, cash, mode) VALUES"
                " ('2026-10-01T15:00:00+00:00', 1, 1, 'dry_run')")
    con.commit()
    con.close()
    repo = TradingRepository(db)
    assert repo.account_start("dry_run") is None
    assert len(repo.equity_series(mode="dry_run")) == 1


def test_the_history_page_says_the_run_it_shows(tmp_path):
    pytest.importorskip("fastapi")
    from tradebot.web.app import create_app

    from .web_client import local_client

    db = str(tmp_path / "t.db")
    _scenario(db)
    client = local_client(create_app(trading_db=db, arena_db=str(tmp_path / "a.db"),
                                     cache_dir=str(tmp_path / "cache")))
    body = client.get("/history").text                 # the newest snapshot is dry_run's
    assert "account dry_run" in body and "since this run started" in body
    with Storage(db) as st:
        st.record_equity(5_050, 5_050, "paper")
    body = client.get("/history").text
    assert "account paper" in body and "since this run started" not in body


def test_a_web_dry_run_build_records_a_start(tmp_path, monkeypatch):
    from .test_web_today import _seed_cache

    monkeypatch.setattr("tradebot.config.AlpacaCredentials.from_env", lambda: None)
    _seed_cache(tmp_path)
    db = str(tmp_path / "t.db")
    settings = Settings(symbols=["SPY", "QQQ"], strategy_name="buy_and_hold")
    for _ in range(2):
        pilot = autopilot_build.build(settings, trading_db=db, cache_dir=str(tmp_path / "cache"))
        pilot.storage.close()
    with Storage(db) as st:
        rows = st._conn.execute("SELECT mode FROM account_starts").fetchall()
    assert [r[0] for r in rows] == ["dry_run", "dry_run"]


def test_a_cli_dry_run_records_a_start(tmp_path, monkeypatch):
    from tradebot.cli import main

    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text(f"symbols: [SPY]\ndb_path: {tmp_path / 't.db'}\n")
    assert main(["run", "--dry-run", "--replay", "--replay-periods", "60",
                 "--iterations", "1"]) == 0
    with Storage(tmp_path / "t.db") as st:
        rows = st._conn.execute("SELECT mode FROM account_starts").fetchall()
    assert [r[0] for r in rows] == ["dry_run"]
