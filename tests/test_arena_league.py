from pathlib import Path

from tradebot.arena.league import LeagueResult, run_league
from tradebot.arena.scenario import Scenario
from tradebot.arena.tournament import run_tournament
from tradebot.cli import main

ALGOS = Path(__file__).resolve().parents[1] / "algos"


def _league(**kw):
    kw.setdefault("isolation", "thread")  # fast, no forking in tests
    return run_league([str(ALGOS)], **kw)


def test_league_produces_snapshots_and_final():
    res = _league(scenario=Scenario(periods=200, seed=1), metric="total_return", snapshots=5)
    assert isinstance(res, LeagueResult)
    assert [s.step for s in res.snapshots] == [1, 2, 3, 4, 5]
    assert all(s.total_steps == 5 for s in res.snapshots)
    # Every snapshot ranks all ok contestants 1..k contiguously.
    for snap in res.snapshots:
        assert [st.rank for st in snap.standings] == list(range(1, len(snap.standings) + 1))


def test_final_snapshot_matches_final_leaderboard_order():
    res = _league(scenario=Scenario(periods=200, seed=2), metric="sharpe", snapshots=4)
    final_ok = [e.name for e in res.final.entries if e.ok]
    last_snapshot = [st.name for st in res.snapshots[-1].standings]
    assert last_snapshot == final_ok


def test_league_final_equals_tournament():
    sc = Scenario(periods=180, seed=3)
    league = _league(scenario=sc, metric="sharpe", snapshots=4)
    tour = run_tournament([str(ALGOS)], sc, metric="sharpe", isolation="thread")
    assert [e.name for e in league.final.entries] == [e.name for e in tour.leaderboard.entries]


def test_snapshots_capped_to_available_bars():
    res = _league(scenario=Scenario(periods=40, seed=1), metric="total_return", snapshots=1000)
    assert 1 <= len(res.snapshots) <= 39          # capped to length-1
    assert res.snapshots[-1].standings             # final snapshot still populated


def test_league_is_deterministic():
    def names(r):
        return [(s.step, [x.name for x in s.standings]) for s in r.snapshots]
    a = _league(scenario=Scenario(periods=150, seed=4), metric="total_return", snapshots=5)
    b = _league(scenario=Scenario(periods=150, seed=4), metric="total_return", snapshots=5)
    assert names(a) == names(b)


def test_cli_arena_league(capsys):
    rc = main(["arena", "league", "--algos", str(ALGOS), "--score", "total_return",
               "--snapshots", "4", "--isolation", "thread"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "League season" in out
    assert "Leaderboard" in out          # final table printed
    assert "[ 4/4" in out or "[4/4" in out  # last snapshot line
