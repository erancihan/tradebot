import pandas as pd
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
        assert {s.name for s in snap.standings} <= {
            "sma_trend", "rsi_dip", "buy_and_hold",
            "donchian", "macd_cross", "bollinger_dip",
            "xs_momentum", "xs_momentum_vt", "xs_reversal", "xs_regime",
            "meta_leader", "meta_vote",
        }


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


def test_live_feed_delivers_a_bar_polled_while_still_forming(tmp_path):
    """Regression: the live feed used to lose every bar it saw form.

    `next()` marked a timestamp seen the moment it was *offered*, and the daemon
    then discarded it as still-forming — so a bar first polled before its close
    was never offered again after it closed. A live daily season accumulated
    zero bars while reporting healthy ticks. Completeness is now filtered inside
    the feed, before the dedup.
    """
    from tradebot.arena.season import AlpacaSeasonFeed

    idx = pd.date_range("2024-01-02", periods=3, freq="1D", tz="UTC")
    df = pd.DataFrame({"open": 100.0, "high": 101.0, "low": 99.0,
                       "close": 100.5, "volume": 1000.0}, index=idx)

    class _Fake:
        def history(self, symbol, timeframe=None, lookback=None):
            return df

    # First poll lands during the last bar's own session (still forming); the
    # second lands after it has closed.
    times = iter([_dt(2024, 1, 4, 17, 0), _dt(2024, 1, 5, 17, 0), _dt(2024, 1, 5, 18, 0)])
    feed = AlpacaSeasonFeed(["DEMO"], "1day", "k", "s",
                            data=_Fake(), clock=lambda: next(times))

    # Poll during the last bar's session: it is still forming, so the feed hands
    # over the newest *settled* bar instead and does not consume the forming one.
    first = feed.next()
    assert first is not None
    assert pd.Timestamp(first["DEMO"].index[-1]) == idx[-2]

    # Poll after it closes: the bar that was forming is now delivered. Under the
    # old order it had already been marked seen and was lost permanently.
    second = feed.next()
    assert second is not None
    assert pd.Timestamp(second["DEMO"].index[-1]) == idx[-1]

    # ...and exactly once: a settled bar is not re-delivered.
    assert feed.next() is None


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


def test_the_recompute_budget_and_sandbox_survive_a_restart(tmp_path):
    """A season's isolation settings are part of its durable config.

    They used to be half-durable: `isolation` round-tripped but the recompute
    hardcoded `harden=False`, so a season created with process isolation ran
    unsandboxed while the tournament reported a clean `ok`. Hardening is now
    derived from the isolation mode, which is the only way the two cannot drift.
    """
    with SeasonStore(tmp_path / "s.db") as store:
        sid = store.create_season(
            _config(isolation="process", time_budget_s=3.5))
        reloaded = store.get_config(sid)

    assert reloaded.isolation == "process"
    assert reloaded.time_budget_s == 3.5
    assert reloaded.hardened is True


def test_a_thread_isolated_season_is_never_reported_as_sandboxed():
    """A thread shares the interpreter: it cannot get its own fs or netns."""
    assert _config(isolation="thread").hardened is False
    assert _config().hardened is False               # thread is the default


def test_an_older_season_row_still_loads(tmp_path):
    """Config JSON predating the budget field must not break on reload."""
    import json

    with SeasonStore(tmp_path / "s.db") as store:
        sid = store.create_season(_config())
        store._conn.execute(
            "UPDATE seasons SET config_json = ? WHERE id = ?",
            (json.dumps({"algo_paths": ["x"]}), sid),
        )
        store._conn.commit()
        old = store.get_config(sid)

    assert old.time_budget_s == 10.0
    assert old.isolation == "thread"


# --- seeding: starting a season warmed up ---------------------------------------

def _seed_frames(periods=80, symbols=("A", "B")):
    import pandas as pd

    idx = pd.date_range("2026-01-02", periods=periods, freq="1D", tz="UTC")
    frames = {}
    for i, sym in enumerate(symbols):
        df = synthetic_ohlcv(periods=periods, seed=i + 1)
        df.index = idx
        frames[sym] = df
    return frames


def test_seeding_backfills_history_and_records_the_boundary(tmp_path):
    """A daily season started from zero measures nothing for months.

    `MomentumSelector(lookback=60)` alone is flat for 61 bars, so the first
    quarter of a fresh season has no contestant deployed. Seeding fixes that,
    and the boundary is recorded because backfilled standings are NOT the same
    claim as live-earned ones.
    """
    from tradebot.arena.season import seed_season

    with SeasonStore(tmp_path / "s.db") as store:
        season = Season.create(store, _config(symbols=["A", "B"]))
        written = seed_season(season, _seed_frames())

        assert written == 160
        assert season.step_index == 80
        assert store.seeded_through(season.id).startswith("2026-03-22")
        assert store.latest_standings(season.id) is not None


def test_seeding_is_idempotent(tmp_path):
    """Bars are keyed on (season, symbol, ts), so re-seeding changes nothing."""
    from tradebot.arena.season import seed_season

    with SeasonStore(tmp_path / "s.db") as store:
        season = Season.create(store, _config(symbols=["A", "B"]))
        frames = _seed_frames()
        seed_season(season, frames, recompute=False)
        before = {s: len(f) for s, f in store.load_frames(season.id).items()}
        seed_season(season, frames, recompute=False)

        assert {s: len(f) for s, f in store.load_frames(season.id).items()} == before


def test_a_seeded_season_resumes_and_keeps_accumulating(tmp_path):
    """The whole point of seeding: warmed up now, live from here."""
    import pandas as pd

    from tradebot.arena.season import seed_season

    db = tmp_path / "s.db"
    with SeasonStore(db) as store:
        season = Season.create(store, _config(symbols=["A", "B"]))
        seed_season(season, _seed_frames())
        season_id = season.id

    # A fresh process would do exactly this: reload and keep stepping.
    with SeasonStore(db) as store:
        resumed = Season.load(store, season_id)
        assert resumed.step_index == 80

        later = pd.date_range("2026-03-23", periods=4, freq="1D", tz="UTC")
        live = {}
        for i, sym in enumerate(["A", "B"]):
            df = synthetic_ohlcv(periods=4, seed=50 + i)
            df.index = later
            live[sym] = df
        assert run_season(resumed, ReplaySeasonFeed(live), max_ticks=4) == 4
        assert resumed.step_index == 84
        # The boundary stays where the seed ended; live bars are past it.
        assert store.seeded_through(season_id).startswith("2026-03-22")


def test_seeding_nothing_is_a_no_op(tmp_path):
    from tradebot.arena.season import seed_season

    with SeasonStore(tmp_path / "s.db") as store:
        season = Season.create(store, _config())
        assert seed_season(season, {}) == 0
        assert store.seeded_through(season.id) is None


def test_an_older_season_db_gains_the_boundary_column(tmp_path):
    """Additive migration: a DB written before seeding existed still opens."""
    import sqlite3

    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE seasons (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            symbols TEXT NOT NULL, timeframe TEXT NOT NULL, metric TEXT NOT NULL,
            config_json TEXT NOT NULL, status TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
    """)
    conn.execute("INSERT INTO seasons (name, symbols, timeframe, metric, config_json,"
                 " status, created_at, updated_at) VALUES"
                 " ('old', 'A', '1day', 'sharpe', '{}', 'created', 'x', 'x')")
    conn.commit()
    conn.close()

    with SeasonStore(db) as store:
        assert store.seeded_through(1) is None
        store.set_seeded_through(1, "2026-01-01T00:00:00+00:00")
        assert store.seeded_through(1).startswith("2026-01-01")


def test_cli_seed_reports_the_boundary_in_standings(tmp_path, capsys):
    from tradebot.data.cache import BarCache

    cache_dir = tmp_path / "cache"
    cache = BarCache(str(cache_dir))
    frames = _seed_frames(periods=70)
    for sym, df in frames.items():
        cache.store(sym, "1day", df)
        cache.record_coverage(sym, "1day", df.index[0], df.index[-1])

    db = str(tmp_path / "s.db")
    assert main(["arena", "season", "create", "--name", "p", "--symbols", "A", "B",
                 "--algos", str(ALGOS), "--score", "total_return", "--db", db]) == 0
    capsys.readouterr()

    assert main(["arena", "season", "seed", "1", "--start", "2026-01-02",
                 "--end", "2026-03-12", "--cache-dir", str(cache_dir),
                 "--db", db]) == 0
    assert "BACKFILLED" in capsys.readouterr().out

    assert main(["arena", "season", "standings", "1", "--db", db]) == 0
    out = capsys.readouterr().out
    assert "seeded through" in out
    assert "not a live-forward result" in out


def test_cli_seed_refuses_when_there_are_no_bars(tmp_path, capsys):
    db = str(tmp_path / "s.db")
    assert main(["arena", "season", "create", "--name", "p", "--symbols", "A",
                 "--algos", str(ALGOS), "--db", db]) == 0
    capsys.readouterr()

    # No cache, no credentials: it must say so rather than seed an empty season.
    assert main(["arena", "season", "seed", "1", "--start", "2026-01-02",
                 "--end", "2026-03-12", "--cache-dir", str(tmp_path / "nope"),
                 "--db", db]) == 2


# --- the live feed must survive downtime ---------------------------------------

class _WindowedData:
    """A provider whose visible history grows — like real bars over real time."""

    def __init__(self, full):
        self.full = full
        self.upto = 0

    def history(self, symbol, timeframe=None, lookback=5):
        return self.full.iloc[max(0, self.upto - lookback):self.upto]


def _daily(periods, seed=1):
    import pandas as pd

    df = synthetic_ohlcv(periods=periods, seed=seed)
    df.index = pd.date_range("2026-01-02", periods=periods, freq="1D", tz="UTC")
    return df


def _settled_clock():
    import pandas as pd

    return lambda: pd.Timestamp("2026-06-01", tz="UTC")   # everything has closed


def test_the_live_feed_delivers_every_bar_missed_while_it_was_down():
    """A gap between polls must not punch a hole in the season's history.

    Returning only the newest bar meant a machine asleep over a weekend, a
    reboot, or a crashed daemon silently lost every bar in between — and because
    standings are recomputed from accumulated bars, a hole quietly changes every
    later ranking while the season still reports healthy. Measured before the
    fix: 7 of 9 bars lost.
    """
    from tradebot.arena.season import AlpacaSeasonFeed

    full = _daily(10)
    data = _WindowedData(full)
    data.upto = 5
    feed = AlpacaSeasonFeed(["X"], "1day", "k", "s", data=data, clock=_settled_clock())

    delivered = list(feed.next()["X"].index)
    data.upto = 9                                  # four sessions passed, unobserved
    delivered += list(feed.next()["X"].index)

    assert set(delivered) == set(full.index[:9])   # nothing lost
    assert delivered == sorted(delivered)          # and still in order


def test_a_settled_bar_is_never_delivered_twice():
    from tradebot.arena.season import AlpacaSeasonFeed

    data = _WindowedData(_daily(6))
    data.upto = 6
    feed = AlpacaSeasonFeed(["X"], "1day", "k", "s", data=data, clock=_settled_clock())

    first = feed.next()
    assert first is not None and len(first["X"]) == 6
    assert feed.next() is None                     # nothing new has settled


def test_a_restarted_feed_re_offers_its_window_rather_than_skipping():
    """`_last_ts` is in memory, so a fresh process starts blind.

    Re-offering is the safe direction: the season's (season, symbol, ts) primary
    key makes it idempotent, so a restart heals the history instead of skipping
    whatever arrived while the daemon was dead.
    """
    from tradebot.arena.season import AlpacaSeasonFeed

    data = _WindowedData(_daily(8))
    data.upto = 8
    clock = _settled_clock()

    AlpacaSeasonFeed(["X"], "1day", "k", "s", data=data, clock=clock).next()
    restarted = AlpacaSeasonFeed(["X"], "1day", "k", "s", data=data, clock=clock)

    again = restarted.next()
    assert again is not None and len(again["X"]) == 8


def test_downtime_longer_than_the_catchup_window_is_bounded_by_it(tmp_path):
    """Honest limit: beyond `catchup` bars, the fix is to re-seed."""
    from tradebot.arena.season import AlpacaSeasonFeed

    full = _daily(40)
    data = _WindowedData(full)
    data.upto = 1
    feed = AlpacaSeasonFeed(["X"], "1day", "k", "s", data=data,
                            clock=_settled_clock(), catchup=5)
    feed.next()

    data.upto = 40                                  # 39 sessions missed
    caught = feed.next()["X"]
    assert len(caught) == 5                         # only the window
    assert caught.index[-1] == full.index[39]


def test_a_caught_up_feed_still_accumulates_correctly(tmp_path):
    """End to end: a gap heals into the season's stored history."""
    from tradebot.arena.season import AlpacaSeasonFeed

    full = _daily(12)
    data = _WindowedData(full)
    data.upto = 4
    feed = AlpacaSeasonFeed(["DEMO"], "1day", "k", "s", data=data,
                            clock=_settled_clock())

    with SeasonStore(tmp_path / "s.db") as store:
        season = Season.create(store, _config(symbols=["DEMO"]))
        season.step(feed.next())
        data.upto = 12
        season.step(feed.next())

        stored = store.load_frames(season.id)["DEMO"]
        assert len(stored) == 12
        assert list(stored.index) == list(full.index)
