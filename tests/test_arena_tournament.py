from pathlib import Path

from tradebot.arena.scenario import Scenario
from tradebot.arena.tournament import run_tournament
from tradebot.cli import main

ALGOS_DIR = Path(__file__).resolve().parents[1] / "algos"


def test_tournament_over_example_algos_ranks_everyone():
    outcome = run_tournament([str(ALGOS_DIR)], Scenario.default(), metric="total_return")
    assert outcome.load_errors == []
    names = {e.name for e in outcome.leaderboard.entries}
    assert {"sma_trend", "rsi_dip", "buy_and_hold"} <= names
    assert all(e.ok for e in outcome.leaderboard.entries)
    assert outcome.leaderboard.entries[0].rank == 1
    # Ranking is consistent with the chosen metric (descending total return).
    returns = [e.total_return for e in outcome.leaderboard.entries]
    assert returns == sorted(returns, reverse=True)


def test_results_are_deterministic():
    a = run_tournament([str(ALGOS_DIR)], Scenario.default(), metric="sharpe")
    b = run_tournament([str(ALGOS_DIR)], Scenario.default(), metric="sharpe")
    assert [(e.name, round(e.total_return, 8)) for e in a.leaderboard.entries] == \
           [(e.name, round(e.total_return, 8)) for e in b.leaderboard.entries]


def test_a_crashing_contestant_is_isolated(tmp_path):
    (tmp_path / "good.py").write_text(
        "from tradebot.arena import register, Algo, Action\n"
        "@register(name='good_algo')\n"
        "class G(Algo):\n"
        "    def on_bar(self, bar, ctx): return Action.long()\n"
    )
    (tmp_path / "bad.py").write_text(
        "from tradebot.arena import register, Algo, Action\n"
        "@register(name='bad_algo')\n"
        "class B(Algo):\n"
        "    def on_bar(self, bar, ctx): raise RuntimeError('boom')\n"
    )
    outcome = run_tournament([str(tmp_path)], Scenario(periods=60, seed=1),
                             metric="total_return")
    by = {e.name: e for e in outcome.leaderboard.entries}
    assert by["good_algo"].ok
    assert by["bad_algo"].status == "error"
    assert "boom" in by["bad_algo"].error


def test_cli_arena_run_prints_leaderboard(capsys):
    rc = main(["arena", "run", "--algos", str(ALGOS_DIR), "--score", "total_return"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Leaderboard" in out
    assert "buy_and_hold" in out


def test_cli_arena_list(capsys):
    rc = main(["arena", "list", "--algos", str(ALGOS_DIR)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "sma_trend" in out and "rsi_dip" in out
