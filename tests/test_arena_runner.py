import time

import pytest

from tradebot.arena.contestant import Contestant
from tradebot.arena.interfaces import Action, Algo
from tradebot.arena.runner import (
    InProcessRunner,
    SubprocessRunner,
    default_runner,
    fork_available,
)
from tradebot.arena.scoring import get_scorer
from tradebot.arena.simulation import SimConfig
from tradebot.data.synthetic import synthetic_ohlcv
from tradebot.risk import RiskConfig, RiskManager

from .arena_files import algo_file, run_file

needs_fork = pytest.mark.skipif(not fork_available(), reason="requires the fork start method")


class _SlowAlgo(Algo):
    """Sleeps on every bar so a full run far exceeds a small time budget."""

    def on_bar(self, bar, ctx) -> Action:
        time.sleep(0.05)
        return Action.flat()


class _FlatAlgo(Algo):
    def on_bar(self, bar, ctx) -> Action:
        return Action.flat()


def _run(factory, budget):
    df = synthetic_ohlcv(periods=40, seed=1)
    runner = InProcessRunner(time_budget_s=budget)
    contestant = Contestant(name="x", factory=factory, kind="event")
    return runner.run(contestant, {"DEMO": df}, RiskManager(RiskConfig()),
                      SimConfig(), get_scorer("total_return"))


def test_timeout_is_enforced_without_blocking():
    # 40 bars * 0.05s ≈ 2s of work, but the budget is 0.1s. If the runner blocked
    # until the work finished, this would take ~2s; it must return promptly.
    start = time.perf_counter()
    result = _run(_SlowAlgo, budget=0.1)
    elapsed = time.perf_counter() - start

    assert result.status == "timeout"
    assert "exceeded" in result.error
    assert elapsed < 1.0          # did not wait for the ~2s of sleeps


def test_fast_contestant_completes_ok():
    result = _run(_FlatAlgo, budget=5.0)
    assert result.status == "ok"
    assert result.result is not None
    assert result.score is not None


# --- SubprocessRunner: hard isolation (POSIX) --------------------------------
# A process-isolated contestant is imported in a fresh interpreter, so it lives
# in a file (`tests/arena_files.py`), not in a class defined here.

def _run_subproc(tmp_path, body, budget, **kw):
    runner = SubprocessRunner(time_budget_s=budget, **kw)
    return run_file(runner, algo_file(tmp_path, body), periods=60)


@needs_fork
def test_subprocess_hard_kills_a_runaway(tmp_path):
    start = time.perf_counter()
    result = _run_subproc(tmp_path, "while True:\n    pass", budget=0.3)
    elapsed = time.perf_counter() - start
    assert result.status == "timeout"
    assert elapsed < 5.0          # killed, not waited out (start-up excluded)


@needs_fork
def test_subprocess_runs_a_normal_contestant(tmp_path):
    result = _run_subproc(tmp_path, "pass", budget=5.0)
    assert result.status == "ok"
    assert result.result is not None and result.score is not None


@needs_fork
def test_subprocess_isolates_a_crash(tmp_path):
    result = _run_subproc(tmp_path, "raise RuntimeError('kaboom')", budget=5.0)
    assert result.status == "error"
    assert "kaboom" in result.error


@needs_fork
def test_subprocess_result_matches_the_in_process_result(tmp_path):
    """The plain-data reply rebuilds the same curve and trades the thread run makes."""
    import pandas as pd

    from tradebot.arena.loader import discover

    path = algo_file(tmp_path, "pass", prelude="""
        from tradebot.strategies import SmaCrossover

        @register(name="trend", author="t")
        class Trend(SmaCrossover):
            def __init__(self):
                super().__init__(fast=5, slow=15)
        """)
    sub = run_file(SubprocessRunner(time_budget_s=10.0), path, name="trend", periods=120)
    (local,) = [c for c in discover([str(path)])[0] if c.name == "trend"]
    df = synthetic_ohlcv(periods=120, seed=1)
    thread = InProcessRunner(10.0).run(local, {"DEMO": df}, RiskManager(RiskConfig()),
                                       SimConfig(), get_scorer("total_return"))
    pd.testing.assert_series_equal(sub.result.equity_curve, thread.result.equity_curve)
    # A trade's `timestamp` is the wall clock at the fill; everything else matches.
    legs = [[(t.symbol, t.qty, t.entry_price, t.exit_price, t.pnl, t.side)
             for t in r.result.trades] for r in (sub, thread)]
    assert legs[0] == legs[1] and sub.result.num_trades > 0
    assert sub.score == thread.score


@needs_fork
def test_default_runner_is_subprocess_on_posix():
    assert isinstance(default_runner(isolation="process"), SubprocessRunner)
    assert isinstance(default_runner(isolation="thread"), InProcessRunner)


def test_default_runner_thread_is_always_in_process():
    assert isinstance(default_runner(isolation="thread"), InProcessRunner)


def test_default_runner_rejects_unknown_isolation():
    with pytest.raises(ValueError):
        default_runner(isolation="bogus")


def test_process_isolation_raises_when_fork_unavailable(monkeypatch):
    # Pretend fork isn't available: 'process' must fail loudly, not downgrade.
    monkeypatch.setattr("tradebot.arena.runner.fork_available", lambda: False)
    with pytest.raises(RuntimeError, match="fork"):
        default_runner(isolation="process")


def test_auto_isolation_falls_back_to_thread_without_fork(monkeypatch):
    monkeypatch.setattr("tradebot.arena.runner.fork_available", lambda: False)
    assert isinstance(default_runner(isolation="auto"), InProcessRunner)


@pytest.mark.parametrize("flag", ["seccomp", "require_sandbox"])
def test_thread_isolation_refuses_sandbox_guarantees_it_cannot_give(flag):
    """`--seccomp` and `--require-sandbox` used to vanish behind a debug log on an
    in-process runner, so the run looked sandboxed and was not."""
    with pytest.raises(ValueError, match="in-process"):
        default_runner(isolation="thread", **{flag: True})


@pytest.mark.parametrize("flag", ["seccomp", "require_sandbox"])
def test_auto_fallback_refuses_sandbox_guarantees_it_cannot_give(monkeypatch, flag):
    monkeypatch.setattr("tradebot.arena.runner.fork_available", lambda: False)
    with pytest.raises(ValueError, match="in-process"):
        default_runner(isolation="auto", **{flag: True})


def test_thread_isolation_still_accepts_the_default_hardening_flag():
    # `harden` is on by default everywhere; only the explicit guarantees refuse.
    assert isinstance(default_runner(isolation="thread", harden=True), InProcessRunner)
