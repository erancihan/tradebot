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


# --- SubprocessRunner: hard isolation (POSIX/fork) ---------------------------

class _BusyAlgo(Algo):
    """A CPU-bound runaway: spins forever on the first decision."""

    def on_bar(self, bar, ctx) -> Action:
        while True:
            pass


def _run_subproc(factory, budget, **kw):
    df = synthetic_ohlcv(periods=60, seed=1)
    runner = SubprocessRunner(time_budget_s=budget, **kw)
    contestant = Contestant(name="x", factory=factory, kind="event")
    return runner.run(contestant, {"DEMO": df}, RiskManager(RiskConfig()),
                      SimConfig(), get_scorer("total_return"))


@needs_fork
def test_subprocess_hard_kills_a_runaway():
    start = time.perf_counter()
    result = _run_subproc(_BusyAlgo, budget=0.3)
    elapsed = time.perf_counter() - start
    assert result.status == "timeout"
    assert elapsed < 3.0          # killed, not waited out


@needs_fork
def test_subprocess_runs_a_normal_contestant():
    result = _run_subproc(_FlatAlgo, budget=5.0)
    assert result.status == "ok"
    assert result.result is not None and result.score is not None


@needs_fork
def test_subprocess_isolates_a_crash():
    class _Boom(Algo):
        def on_bar(self, bar, ctx) -> Action:
            raise RuntimeError("kaboom")

    result = _run_subproc(_Boom, budget=5.0)
    assert result.status == "error"
    assert "kaboom" in result.error


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
