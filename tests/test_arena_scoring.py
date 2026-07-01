import pytest

from tradebot.arena.contestant import Contestant
from tradebot.arena.result import ERROR, OK, ContestantResult, Leaderboard
from tradebot.arena.scoring import available, get_scorer


def test_available_metrics():
    assert {"sharpe", "total_return", "cagr", "calmar"} <= set(available())


def test_unknown_metric_raises():
    with pytest.raises(ValueError):
        get_scorer("nope")


def test_calmar_is_cagr_over_drawdown():
    class _R:
        cagr = 0.2
        max_drawdown = -0.1

    assert get_scorer("calmar")(_R()) == pytest.approx(2.0)


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
