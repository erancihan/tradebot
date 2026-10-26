from pathlib import Path

from tradebot.arena.scenario import Scenario
from tradebot.arena.tournament import run_tournament
from tradebot.cli import main

ALGOS_DIR = Path(__file__).resolve().parents[1] / "algos"


def test_tournament_over_example_algos_ranks_everyone():
    outcome = run_tournament([str(ALGOS_DIR)], Scenario.default(), metric="total_return")
    assert outcome.load_errors == []
    names = {e.name for e in outcome.leaderboard.entries}
    assert {"sma_trend", "rsi_dip", "buy_and_hold",
            "donchian", "macd_cross", "bollinger_dip",
            "xs_momentum", "xs_momentum_vt", "xs_reversal", "xs_regime",
            "meta_leader", "meta_vote"} <= names
    assert all(e.ok for e in outcome.leaderboard.entries)
    assert outcome.leaderboard.entries[0].rank == 1
    # Ranking is consistent with the chosen metric (descending total return).
    returns = [e.total_return for e in outcome.leaderboard.entries]
    assert returns == sorted(returns, reverse=True)


def test_tournament_ranks_by_robustness_metric_on_a_regime_scenario():
    scenario = Scenario.from_yaml(Path(__file__).resolve().parents[1]
                                  / "scenarios" / "crash_recovery.yaml")
    outcome = run_tournament([str(ALGOS_DIR)], scenario, metric="worst_fold",
                             isolation="thread")
    ok = [e for e in outcome.leaderboard.entries if e.ok]
    assert ok and all(e.score is not None for e in ok)
    scores = [e.score for e in ok]
    assert scores == sorted(scores, reverse=True)


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


def test_cli_arena_run_prints_leaderboard(tmp_path, capsys):
    rc = main(["arena", "run", "--algos", str(ALGOS_DIR), "--score", "total_return",
               "--db", str(tmp_path / "arena.db")])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Leaderboard" in out
    assert "buy_and_hold" in out


def test_cli_arena_list(capsys):
    rc = main(["arena", "list", "--algos", str(ALGOS_DIR)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "sma_trend" in out and "rsi_dip" in out


_WRITING_ALGO = (
    "import pathlib\n"
    "pathlib.Path({marker!r}).write_text('parent')\n"
    "from tradebot.arena import Action, Algo, register\n"
    "@register(name='side_effect_algo', author='t')\n"
    "class Spy(Algo):\n"
    "    def on_bar(self, bar, ctx): return Action.flat()\n"
)


def test_cli_arena_list_imports_in_a_sandbox_not_the_parent(tmp_path, capsys):
    """``arena list`` runs module bodies: they run in a hardened child, as under
    ``run``, so a body that writes is refused and reported, never listed."""
    marker = tmp_path / "touched"
    algo = tmp_path / "spy.py"
    algo.write_text(_WRITING_ALGO.format(marker=str(marker)))
    rc = main(["arena", "list", "--algos", str(algo)])
    assert rc == 0
    out, err = capsys.readouterr()
    assert "side_effect_algo" not in out and "load error" in err
    # Landlock leaves no file; the size cap (macOS) leaves an empty one. Never
    # the body's content, and never from this interpreter.
    assert not marker.exists() or marker.read_text() == ""


def test_cli_arena_list_thread_isolation_imports_in_process(tmp_path, capsys):
    marker = tmp_path / "touched"
    algo = tmp_path / "plain.py"
    algo.write_text(_WRITING_ALGO.format(marker=str(marker)))
    rc = main(["arena", "list", "--algos", str(algo), "--isolation", "thread"])
    assert rc == 0 and "side_effect_algo" in capsys.readouterr().out
    assert marker.read_text() == "parent"   # the trusting loader, by request
