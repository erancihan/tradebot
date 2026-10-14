import numpy as np
import pandas as pd
import pytest

from tradebot.arena.contestant import Contestant
from tradebot.arena.result import ERROR, OK, ContestantResult, Leaderboard
from tradebot.arena.scoring import available, fold_returns, get_scorer
from tradebot.backtest import BacktestResult


def test_available_metrics():
    assert {"sharpe", "total_return", "cagr", "calmar",
            "worst_fold", "consistency"} <= set(available())


def test_unknown_metric_raises():
    with pytest.raises(ValueError):
        get_scorer("nope")


def test_calmar_is_cagr_over_drawdown():
    class _R:
        cagr = 0.2
        max_drawdown = -0.1

    assert get_scorer("calmar")(_R()) == pytest.approx(2.0)


def _bt_result(equity: list[float]) -> BacktestResult:
    curve = pd.Series(equity,
                      index=pd.date_range("2023-01-02", periods=len(equity),
                                          freq="1D", tz="UTC"),
                      dtype=float)
    return BacktestResult(equity_curve=curve, trades=[], initial_cash=equity[0])


def test_fold_returns_chain_to_the_total_return():
    r = _bt_result(list(np.linspace(100, 180, 41)))
    rs = fold_returns(r, folds=4)
    assert len(rs) == 4
    compounded = float(np.prod([1 + x for x in rs])) - 1.0
    assert compounded == pytest.approx(r.total_return)


def test_worst_fold_flags_a_hidden_crash():
    # Same start and end, but one path crashes in the third quarter.
    # 41 points -> 40 returns -> four equal 10-return folds.
    final = 100 * 1.005 ** 40
    steady = _bt_result(list(100 * 1.005 ** np.arange(41)))
    lumpy = _bt_result(list(np.linspace(100, 140, 21))
                       + list(np.linspace(140, 90, 11))[1:]
                       + list(np.linspace(90, final, 11))[1:])
    assert steady.final_equity == pytest.approx(lumpy.final_equity)

    worst = get_scorer("worst_fold")
    assert worst(steady) > 0
    assert worst(lumpy) < 0                     # the crash fold shows up
    assert worst(steady) > worst(lumpy)


def test_consistency_prefers_even_earnings():
    steady = _bt_result(list(100 * 1.005 ** np.arange(41)))
    lumpy = _bt_result([100.0] * 31 + list(np.linspace(100, 100 * 1.005 ** 40, 10)))
    score = get_scorer("consistency")
    assert score(steady) > score(lumpy)
    # Perfectly even geometric growth has zero fold dispersion.
    rs = fold_returns(steady, folds=4)
    assert max(rs) - min(rs) == pytest.approx(0.0, abs=1e-12)


def test_fold_scorers_survive_tiny_curves():
    tiny = _bt_result([100.0, 101.0])
    assert np.isfinite(get_scorer("worst_fold")(tiny))
    assert np.isfinite(get_scorer("consistency")(tiny))
    one = _bt_result([100.0])
    assert get_scorer("worst_fold")(one) == 0.0


def _result(name, score, status=OK):
    c = Contestant(name=name, factory=lambda: None, kind="event")
    return ContestantResult(c, status=status, score=score, result=None)


def test_leaderboard_ranks_by_score_and_sinks_failures():
    board = Leaderboard.build(
        "sharpe",
        [_result("a", 1.0), _result("b", 3.0), _result("c", 2.0),
         _result("boom", None, ERROR)],
    )
    names = [e.name for e in board.entries]
    assert names[:3] == ["b", "c", "a"]      # descending by score
    assert names[-1] == "boom"               # failure last
    assert board.entries[0].rank == 1
    assert board.entries[-1].rank is None
    assert board.winner.name == "b"


def test_table_renders_without_error():
    board = Leaderboard.build("sharpe", [_result("a", 1.0), _result("boom", None, ERROR)])
    text = board.table()
    assert "Leaderboard" in text and "a" in text and "BOOM".lower() in text.lower()
