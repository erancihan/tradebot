"""The experiment journal: multiple-testing accounting for algo research."""

from pathlib import Path

from tradebot.arena.scenario import Scenario
from tradebot.arena.store import ArenaStore
from tradebot.arena.tournament import run_tournament
from tradebot.cli import main

ALGOS_DIR = Path(__file__).resolve().parents[1] / "algos"


def _variants_dir(tmp_path):
    """Three contestants: two variants of one family + one standalone."""
    d = tmp_path / "variants"
    d.mkdir()
    (d / "donchians.py").write_text(
        "from tradebot.arena import register\n"
        "from tradebot.strategies import DonchianBreakout\n"
        "@register(name='donchian_20_10', family='donchian')\n"
        "class D1(DonchianBreakout):\n"
        "    def __init__(self): super().__init__(entry=20, exit=10)\n"
        "@register(name='donchian_55_20', family='donchian')\n"
        "class D2(DonchianBreakout):\n"
        "    def __init__(self): super().__init__(entry=55, exit=20)\n"
        "@register(name='lonesome')\n"
        "class D3(DonchianBreakout):\n"
        "    def __init__(self): super().__init__(entry=30, exit=15)\n"
    )
    return d


def test_register_family_defaults_to_name(tmp_path):
    from tradebot.arena.loader import discover

    contestants, errors = discover([str(_variants_dir(tmp_path))])
    assert errors == []
    fams = {c.name: c.family for c in contestants}
    assert fams == {"donchian_20_10": "donchian", "donchian_55_20": "donchian",
                    "lonesome": "lonesome"}


def test_attempts_are_grouped_by_family(tmp_path):
    scenario = Scenario(name="jrnl", periods=120, seed=1)
    outcome = run_tournament([str(_variants_dir(tmp_path))], scenario,
                             metric="total_return", isolation="thread")
    with ArenaStore(tmp_path / "a.db") as store:
        assert store.record_attempts(scenario, "total_return", outcome) == 3
        # A second evaluation pass burns three more attempts.
        store.record_attempts(scenario, "sharpe", outcome)
        summary = {r["family"]: r for r in store.journal_summary()}

    assert summary["donchian"]["attempts"] == 4
    assert summary["donchian"]["variants"] == 2
    assert summary["lonesome"]["attempts"] == 2
    best = summary["donchian"]["best"]
    assert best is not None and best["name"].startswith("donchian")
    # Scores rank, balances tell the money story: both are recorded,
    # along with the simulated data window.
    assert best["start_balance"] == 10_000.0
    assert best["final_balance"] > 0
    assert best["start_date"].startswith("2023-01")     # synthetic epoch
    assert best["end_date"] > best["start_date"]


def test_failures_still_burn_an_attempt(tmp_path):
    d = tmp_path / "algos"
    d.mkdir()
    (d / "bad.py").write_text(
        "from tradebot.arena import register, Algo, Action\n"
        "@register(name='boomer', family='boom')\n"
        "class B(Algo):\n"
        "    def on_bar(self, bar, ctx): raise RuntimeError('boom')\n"
    )
    scenario = Scenario(name="jrnl", periods=60, seed=1)
    outcome = run_tournament([str(d)], scenario, metric="sharpe", isolation="thread")
    with ArenaStore(tmp_path / "a.db") as store:
        store.record_attempts(scenario, "sharpe", outcome)
        rows = store.journal_entries("boom")
        summary = store.journal_summary()

    assert len(rows) == 1
    assert rows[0]["status"] == "error" and rows[0]["score"] is None
    assert rows[0]["start_balance"] is None and rows[0]["final_balance"] is None
    assert rows[0]["start_date"] is None and rows[0]["end_date"] is None
    assert summary[0]["family"] == "boom" and summary[0]["best"] is None


def test_old_journals_gain_balance_columns_on_open(tmp_path):
    """A pre-balance journal DB is migrated in place when reopened."""
    import sqlite3

    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE experiments (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " ts TEXT NOT NULL, family TEXT NOT NULL, name TEXT NOT NULL,"
        " scenario TEXT NOT NULL, metric TEXT NOT NULL, score REAL,"
        " status TEXT NOT NULL, run_id INTEGER)"
    )
    conn.execute(
        "INSERT INTO experiments (ts, family, name, scenario, metric, score, status)"
        " VALUES ('2026-01-01T00:00:00', 'f', 'f', 's', 'sharpe', 1.0, 'ok')"
    )
    conn.commit()
    conn.close()

    with ArenaStore(db) as store:
        rows = store.journal_entries("f")
        assert rows[0]["start_balance"] is None      # old rows: unknown balances
        best = store.journal_summary()[0]["best"]
        assert best["score"] == 1.0 and best["start_balance"] is None


def test_cli_run_journals_by_default(tmp_path, capsys):
    db = str(tmp_path / "arena.db")
    assert main(["arena", "run", "--algos", str(ALGOS_DIR), "--score", "total_return",
                 "--isolation", "thread", "--db", db]) == 0
    assert "Journaled 12 attempt(s)" in capsys.readouterr().out

    assert main(["arena", "journal", "--db", db]) == 0
    out = capsys.readouterr().out
    assert "attempts per algorithm family" in out
    assert "donchian" in out and "macd_cross" in out
    assert "10,000 -> " in out                    # balance change beside the score
    assert "2023-01-02 -> " in out                # ...and the simulated window

    # Family detail view lists individual attempts (with balances + period).
    assert main(["arena", "journal", "--db", db, "--family", "donchian"]) == 0
    out = capsys.readouterr().out
    assert "family 'donchian'" in out and "default" in out
    assert "balance" in out and "10,000 -> " in out
    assert "simulated period" in out and "2023-01-02 -> " in out

    # A second run trips the multiple-testing reminder.
    assert main(["arena", "run", "--algos", str(ALGOS_DIR), "--score", "sharpe",
                 "--isolation", "thread", "--db", db]) == 0
    capsys.readouterr()
    assert main(["arena", "journal", "--db", db]) == 0
    assert "best-of-N" in capsys.readouterr().out


def test_cli_no_journal_opts_out(tmp_path, capsys):
    db = str(tmp_path / "arena.db")
    assert main(["arena", "run", "--algos", str(ALGOS_DIR), "--score", "total_return",
                 "--isolation", "thread", "--no-journal", "--db", db]) == 0
    assert "Journaled" not in capsys.readouterr().out

    assert main(["arena", "journal", "--db", db]) == 0
    assert "No attempts journaled yet" in capsys.readouterr().out

    assert main(["arena", "journal", "--db", db, "--family", "nope"]) == 0
    assert "No attempts recorded for family" in capsys.readouterr().out


def test_saved_runs_link_journal_rows_to_the_run(tmp_path, capsys):
    db = str(tmp_path / "arena.db")
    assert main(["arena", "run", "--algos", str(ALGOS_DIR), "--score", "total_return",
                 "--isolation", "thread", "--save", "--db", db]) == 0
    capsys.readouterr()
    with ArenaStore(db) as store:
        run_id = store.latest_run_id()
        rows = store.journal_entries("buy_and_hold")
    assert run_id is not None
    assert rows and rows[0]["run_id"] == run_id
