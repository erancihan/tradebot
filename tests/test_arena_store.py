import json
from pathlib import Path

import pandas as pd

from tradebot.arena.scenario import Scenario
from tradebot.arena.store import ArenaStore, equity_to_json
from tradebot.arena.tournament import run_tournament
from tradebot.cli import main

ALGOS_DIR = Path(__file__).resolve().parents[1] / "algos"


def _run(scenario, metric="total_return"):
    return run_tournament([str(ALGOS_DIR)], scenario, metric=metric)


def test_record_and_get_run(tmp_path):
    scenario = Scenario(name="t", symbols=["DEMO"], periods=120, seed=1)
    outcome = _run(scenario)
    with ArenaStore(tmp_path / "arena.db") as store:
        run_id = store.record_run(scenario, "total_return", outcome)
        runs = store.list_runs()
        data = store.get_run(run_id)
        assert store.latest_run_id() == run_id

    assert run_id == 1
    assert len(runs) == 1 and runs[0]["winner"] is not None
    names = {r["name"] for r in data["results"]}
    assert {"sma_trend", "rsi_dip", "buy_and_hold"} <= names
    # Equity curve persisted for every finisher (for later charting).
    ok = [r for r in data["results"] if r["status"] == "ok"]
    assert ok and all(r["equity_json"] for r in ok)
    parsed = json.loads(ok[0]["equity_json"])
    assert len(parsed["index"]) == len(parsed["equity"]) > 0


def test_render_run_matches_live_table(tmp_path):
    scenario = Scenario(name="t", periods=150, seed=2)
    outcome = _run(scenario, metric="sharpe")
    with ArenaStore(tmp_path / "a.db") as store:
        run_id = store.record_run(scenario, "sharpe", outcome)
        rendered = store.render_run(run_id)
    assert rendered == outcome.leaderboard.table()


def test_history_orders_newest_first(tmp_path):
    db = tmp_path / "a.db"
    s1 = Scenario(name="r1", periods=100, seed=1)
    s2 = Scenario(name="r2", periods=100, seed=2)
    with ArenaStore(db) as store:
        store.record_run(s1, "sharpe", _run(s1, "sharpe"))
        store.record_run(s2, "sharpe", _run(s2, "sharpe"))
        runs = store.list_runs()
    assert [r["scenario"] for r in runs] == ["r2", "r1"]
    assert runs[0]["id"] == 2


def test_missing_run_returns_none(tmp_path):
    with ArenaStore(tmp_path / "a.db") as store:
        assert store.get_run(999) is None
        assert store.render_run(999) is None
        assert store.latest_run_id() is None


def test_equity_to_json_shape():
    s = pd.Series([1.0, 2.5], index=pd.to_datetime(["2023-01-01", "2023-01-02"], utc=True))
    d = json.loads(equity_to_json(s))
    assert d["equity"] == [1.0, 2.5]
    assert len(d["index"]) == 2


def test_cli_run_save_history_show(tmp_path, capsys):
    db = str(tmp_path / "arena.db")
    assert main(["arena", "run", "--algos", str(ALGOS_DIR),
                 "--score", "total_return", "--save", "--db", db]) == 0
    assert "Saved as run #1" in capsys.readouterr().out

    assert main(["arena", "history", "--db", db]) == 0
    hist = capsys.readouterr().out
    assert "winner" in hist and "default" in hist

    assert main(["arena", "show", "--db", db]) == 0   # defaults to latest
    shown = capsys.readouterr().out
    assert "Run #1" in shown and "buy_and_hold" in shown
