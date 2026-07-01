from pathlib import Path

from tradebot.arena.season import (
    ReplaySeasonFeed,
    Season,
    SeasonConfig,
    SeasonStore,
    run_season,
)
from tradebot.cli import main
from tradebot.data.synthetic import synthetic_ohlcv

ALGOS = Path(__file__).resolve().parents[1] / "algos"


def _config(**kw):
    kw.setdefault("name", "t")
    kw.setdefault("symbols", ["DEMO"])
    kw.setdefault("metric", "total_return")
    kw.setdefault("algo_paths", [str(ALGOS)])
    return SeasonConfig(**kw)


def test_store_roundtrips_bars_and_config(tmp_path):
    with SeasonStore(tmp_path / "s.db") as store:
        sid = store.create_season(_config(symbols=["A", "B"], algo_paths=["x"]))
        df = synthetic_ohlcv(periods=5, seed=1)
        store.append_bars(sid, {"A": df.iloc[[0]], "B": df.iloc[[0]]})
        store.append_bars(sid, {"A": df.iloc[[1]], "B": df.iloc[[1]]})
        store.append_bars(sid, {"A": df.iloc[[1]], "B": df.iloc[[1]]})  # duplicate

        frames = store.load_frames(sid)
        assert set(frames) == {"A", "B"}
        assert len(frames["A"]) == 2          # duplicate ignored (idempotent)
        cfg = store.get_config(sid)
        assert cfg.symbols == ["A", "B"] and cfg.algo_paths == ["x"]


def test_step_accumulates_then_ranks(tmp_path):
    with SeasonStore(tmp_path / "s.db") as store:
        season = Season.create(store, _config())
        df = synthetic_ohlcv(periods=10, seed=1)
        assert season.step({"DEMO": df.iloc[[0]]}) is None     # one bar: too few
        snap = season.step({"DEMO": df.iloc[[1]]})
        assert snap is not None and snap.step == 2
        assert [s.rank for s in snap.standings] == list(range(1, len(snap.standings) + 1))
        assert {s.name for s in snap.standings} <= {"sma_trend", "rsi_dip", "buy_and_hold"}


def test_season_survives_restart_and_resumes(tmp_path):
    db = tmp_path / "s.db"
    bars = synthetic_ohlcv(periods=20, seed=1)

    # Run the first 5 ticks, then drop everything (simulate a crash/restart).
    with SeasonStore(db) as store:
        season = Season.create(store, _config())
        sid = season.id
        run_season(season, ReplaySeasonFeed({"DEMO": bars.iloc[:5]}), max_ticks=5)
        assert season.step_index == 5

    # Re-open the DB and load the season — state must be exactly where we left it.
    with SeasonStore(db) as store2:
        resumed = Season.load(store2, sid)
        assert resumed.step_index == 5
        assert resumed.config.metric == "total_return"
        # Continue with the next bars; the season keeps growing from disk state.
        run_season(resumed, ReplaySeasonFeed({"DEMO": bars.iloc[5:10]}), max_ticks=5)
        assert resumed.step_index == 10
        assert len(store2.load_frames(sid)["DEMO"]) == 10
        assert store2.latest_standings(sid).step == 10


def test_season_standings_are_deterministic(tmp_path):
    def run(db):
        with SeasonStore(db) as store:
            season = Season.create(store, _config(metric="sharpe"))
            run_season(season, ReplaySeasonFeed({"DEMO": synthetic_ohlcv(periods=30, seed=2)}),
                       max_ticks=30)
            return store.latest_standings(season.id)
    a = run(tmp_path / "a.db")
    b = run(tmp_path / "b.db")
    assert [(s.name, round(s.total_return, 8)) for s in a.standings] == \
           [(s.name, round(s.total_return, 8)) for s in b.standings]


class _FlakySeason:
    """A fake season whose 2nd tick raises, to exercise supervision."""

    def __init__(self):
        self.calls = 0

    def step(self, bar):
        self.calls += 1
        if self.calls == 2:
            raise RuntimeError("boom")
        return None


class _CountFeed:
    def __init__(self, n):
        self.n, self.i = n, 0

    def next(self):
        if self.i >= self.n:
            return None
        self.i += 1
        return {"X": None}


def test_run_season_supervises_tick_errors():
    from tradebot.arena.season import run_season

    errors = []
    ticks = run_season(_FlakySeason(), _CountFeed(4),
                       supervise=True, on_error=errors.append)
    assert ticks == 4 and len(errors) == 1   # one tick failed, loop carried on


def test_run_season_without_supervise_propagates():
    import pytest as _pytest

    from tradebot.arena.season import run_season
    with _pytest.raises(RuntimeError):
        run_season(_FlakySeason(), _CountFeed(4))


def _dt(y, m, d, h, mi=0):
    from datetime import datetime, timezone
    return datetime(y, m, d, h, mi, tzinfo=timezone.utc)


def test_daemon_gates_on_market_hours(tmp_path):
    from tradebot.arena.season import run_season_daemon

    closed = _dt(2024, 1, 6, 15, 0)      # Saturday
    open_ = _dt(2024, 1, 3, 14, 30)      # Wed 09:30 ET
    times = iter([closed, open_, open_, open_, open_, open_])
    with SeasonStore(tmp_path / "s.db") as store:
        season = Season.create(store, _config())
        feed = ReplaySeasonFeed({"DEMO": synthetic_ohlcv(periods=20, seed=1)})
        ticks = run_season_daemon(season, feed, poll_seconds=0, max_ticks=3,
                                  clock=lambda: next(times), sleep=lambda s: None)
        assert ticks == 3                            # closed tick skipped, 3 steps
        assert store.step_count(season.id) >= 1      # standings recorded


def test_daemon_ignore_market_hours_steps_when_closed(tmp_path):
    from tradebot.arena.season import run_season_daemon

    closed = _dt(2024, 1, 6, 15, 0)
    with SeasonStore(tmp_path / "s.db") as store:
        season = Season.create(store, _config())
        feed = ReplaySeasonFeed({"DEMO": synthetic_ohlcv(periods=20, seed=1)})
        ticks = run_season_daemon(season, feed, poll_seconds=0, max_ticks=3,
                                  ignore_market_hours=True,
                                  clock=lambda: closed, sleep=lambda s: None)
        assert ticks == 3


def test_daemon_stops_when_replay_feed_exhausted(tmp_path):
    from tradebot.arena.season import run_season_daemon

    open_ = _dt(2024, 1, 3, 14, 30)
    with SeasonStore(tmp_path / "s.db") as store:
        season = Season.create(store, _config())
        feed = ReplaySeasonFeed({"DEMO": synthetic_ohlcv(periods=8, seed=1)})
        ticks = run_season_daemon(season, feed, poll_seconds=0, stop_on_empty=True,
                                  clock=lambda: open_, sleep=lambda s: None)
        assert ticks == 8                            # all bars consumed, then stop


def test_cli_season_run_simulate(tmp_path, capsys):
    db = str(tmp_path / "season.db")
    main(["arena", "season", "create", "--name", "sim", "--symbols", "DEMO",
          "--algos", str(ALGOS), "--score", "total_return", "--db", db])
    capsys.readouterr()
    assert main(["arena", "season", "run", "1", "--simulate",
                 "--replay-periods", "30", "--db", db]) == 0
    assert "simulated daemon" in capsys.readouterr().out


def test_cli_season_create_run_standings(tmp_path, capsys):
    db = str(tmp_path / "season.db")
    assert main(["arena", "season", "create", "--name", "wk", "--symbols", "DEMO",
                 "--algos", str(ALGOS), "--score", "total_return", "--db", db]) == 0
    assert "Created season #1" in capsys.readouterr().out

    assert main(["arena", "season", "run", "1", "--replay", "--replay-periods", "30",
                 "--db", db]) == 0
    assert "[" in capsys.readouterr().out          # standings lines streamed

    assert main(["arena", "season", "standings", "1", "--db", db]) == 0
    assert "standings" in capsys.readouterr().out.lower()

    assert main(["arena", "season", "list", "--db", db]) == 0
    assert "wk" in capsys.readouterr().out
