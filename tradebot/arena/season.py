"""Real-time league with a durable, resumable *season*.

A season runs the field over wall-clock time: on each tick a new bar arrives,
gets appended to the season's shared bar history (persisted to SQLite), and the
field is re-ranked over everything seen so far. The standings are recorded each
tick, so the season survives restarts — reload it and keep stepping.

Design (reuse-heavy, drift-free):
- The **bars are the source of truth.** Standings are recomputed each tick by
  ``run_tournament`` over the accumulated frames (each contestant is
  look-ahead-safe and deterministic, so re-ranking the full history is exactly
  what a true streamed run would have shown — no per-contestant state to persist
  or risk corrupting). Recompute is O(history) per tick, fine for daily cadence.
- The **feed** is abstracted: ``ReplaySeasonFeed`` drives it offline/in tests;
  an Alpaca-backed feed (lazy) drives it live. ``Season.step`` only ever sees a
  dict of one-bar-per-symbol, so the engine is fully testable without a network.

What is NOT covered here (the remaining real-time operational layer): a hardened
long-running daemon, market-hours/holiday scheduling, and partial-bar handling.
``run_season`` is a thin loop; for production you'd drive ``step`` from cron or a
supervised service.
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from ..models import BAR_COLUMNS, utcnow
from ..risk import RiskConfig
from .league import Standing, StandingsSnapshot
from .scenario import Scenario
from .tournament import run_tournament

_SCHEMA = """
CREATE TABLE IF NOT EXISTS seasons (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    symbols     TEXT NOT NULL,
    timeframe   TEXT NOT NULL,
    metric      TEXT NOT NULL,
    config_json TEXT NOT NULL,
    status      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS season_bars (
    season_id INTEGER NOT NULL,
    symbol    TEXT NOT NULL,
    ts        TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL, volume REAL,
    PRIMARY KEY (season_id, symbol, ts)
);
CREATE TABLE IF NOT EXISTS season_standings (
    season_id      INTEGER NOT NULL,
    step           INTEGER NOT NULL,
    ts             TEXT NOT NULL,
    standings_json TEXT NOT NULL,
    PRIMARY KEY (season_id, step)
);
"""


@dataclass
class SeasonConfig:
    name: str
    symbols: list[str]
    timeframe: str = "1day"
    metric: str = "sharpe"
    algo_paths: list[str] = field(default_factory=list)
    initial_cash: float = 10_000.0
    max_position_pct: float = 0.95
    slippage_bps: float = 1.0
    isolation: str = "thread"   # season recompute runs every tick; thread is light

    def scenario(self) -> Scenario:
        return Scenario(
            name=self.name, symbols=list(self.symbols),
            initial_cash=self.initial_cash, slippage_bps=self.slippage_bps,
            risk=RiskConfig(max_position_pct=self.max_position_pct, max_daily_loss_pct=1.0),
        )

    def to_json(self) -> str:
        return json.dumps({
            "algo_paths": self.algo_paths, "initial_cash": self.initial_cash,
            "max_position_pct": self.max_position_pct, "slippage_bps": self.slippage_bps,
            "isolation": self.isolation,
        })


class SeasonStore:
    def __init__(self, path: str | Path = "season.db") -> None:
        self.path = str(path)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        with closing(self._conn.cursor()) as cur:
            cur.executescript(_SCHEMA)
        self._conn.commit()

    def create_season(self, config: SeasonConfig) -> int:
        now = utcnow().isoformat()
        cur = self._conn.execute(
            "INSERT INTO seasons (name, symbols, timeframe, metric, config_json, status,"
            " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (config.name, ",".join(config.symbols), config.timeframe, config.metric,
             config.to_json(), "created", now, now),
        )
        self._conn.commit()
        return cur.lastrowid

    def get_config(self, season_id: int) -> SeasonConfig | None:
        row = self._conn.execute("SELECT * FROM seasons WHERE id = ?", (season_id,)).fetchone()
        if row is None:
            return None
        extra = json.loads(row["config_json"])
        return SeasonConfig(
            name=row["name"], symbols=row["symbols"].split(","),
            timeframe=row["timeframe"], metric=row["metric"],
            algo_paths=extra.get("algo_paths", []),
            initial_cash=extra.get("initial_cash", 10_000.0),
            max_position_pct=extra.get("max_position_pct", 0.95),
            slippage_bps=extra.get("slippage_bps", 1.0),
            isolation=extra.get("isolation", "thread"),
        )

    def list_seasons(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, name, symbols, timeframe, metric, status, updated_at FROM seasons"
            " ORDER BY id DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def append_bars(self, season_id: int, bars_by_symbol: dict[str, pd.DataFrame]) -> None:
        for symbol, df in bars_by_symbol.items():
            for ts, row in df.iterrows():
                self._conn.execute(
                    "INSERT OR IGNORE INTO season_bars"
                    " (season_id, symbol, ts, open, high, low, close, volume)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (season_id, symbol, pd.Timestamp(ts).isoformat(),
                     float(row["open"]), float(row["high"]), float(row["low"]),
                     float(row["close"]), float(row["volume"])),
                )
        self._conn.execute("UPDATE seasons SET updated_at = ? WHERE id = ?",
                           (utcnow().isoformat(), season_id))
        self._conn.commit()

    def load_frames(self, season_id: int) -> dict[str, pd.DataFrame]:
        rows = self._conn.execute(
            "SELECT symbol, ts, open, high, low, close, volume FROM season_bars"
            " WHERE season_id = ? ORDER BY ts", (season_id,)
        ).fetchall()
        by_symbol: dict[str, list] = {}
        for r in rows:
            by_symbol.setdefault(r["symbol"], []).append(r)
        frames: dict[str, pd.DataFrame] = {}
        for symbol, rs in by_symbol.items():
            idx = pd.to_datetime([r["ts"] for r in rs], utc=True)
            frames[symbol] = pd.DataFrame(
                {c: [r[c] for r in rs] for c in BAR_COLUMNS}, index=idx
            )
        return frames

    def record_standings(self, season_id: int, step: int, ts: str,
                         standings: list[Standing]) -> None:
        payload = json.dumps([
            {"rank": s.rank, "name": s.name, "author": s.author, "score": s.score,
             "total_return": s.total_return, "equity": s.equity}
            for s in standings
        ])
        self._conn.execute(
            "INSERT OR REPLACE INTO season_standings (season_id, step, ts, standings_json)"
            " VALUES (?, ?, ?, ?)", (season_id, step, ts, payload),
        )
        self._conn.commit()

    def step_count(self, season_id: int) -> int:
        row = self._conn.execute(
            "SELECT MAX(step) AS m FROM season_standings WHERE season_id = ?", (season_id,)
        ).fetchone()
        return row["m"] or 0

    def latest_standings(self, season_id: int) -> StandingsSnapshot | None:
        row = self._conn.execute(
            "SELECT step, ts, standings_json FROM season_standings WHERE season_id = ?"
            " ORDER BY step DESC LIMIT 1", (season_id,)
        ).fetchone()
        if row is None:
            return None
        standings = [Standing(**s) for s in json.loads(row["standings_json"])]
        return StandingsSnapshot(step=row["step"], total_steps=row["step"],
                                 timestamp=row["ts"], standings=standings)

    def set_status(self, season_id: int, status: str) -> None:
        self._conn.execute("UPDATE seasons SET status = ?, updated_at = ? WHERE id = ?",
                           (status, utcnow().isoformat(), season_id))
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "SeasonStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def _standings_from_leaderboard(leaderboard) -> list[Standing]:
    out = []
    for e in leaderboard.entries:
        if not e.ok or e.result is None:
            continue
        out.append(Standing(
            rank=e.rank, name=e.name, author=e.author, score=e.score,
            total_return=e.total_return, equity=float(e.result.equity_curve.iloc[-1]),
        ))
    return out


class Season:
    """A resumable league season backed by a :class:`SeasonStore`."""

    def __init__(self, store: SeasonStore, season_id: int, config: SeasonConfig) -> None:
        self.store = store
        self.id = season_id
        self.config = config

    @classmethod
    def create(cls, store: SeasonStore, config: SeasonConfig) -> "Season":
        return cls(store, store.create_season(config), config)

    @classmethod
    def load(cls, store: SeasonStore, season_id: int) -> "Season":
        config = store.get_config(season_id)
        if config is None:
            raise KeyError(f"No season with id {season_id}")
        return cls(store, season_id, config)

    @property
    def step_index(self) -> int:
        return self.store.step_count(self.id)

    def step(self, bars_by_symbol: dict[str, pd.DataFrame]) -> StandingsSnapshot | None:
        """Apply one tick: persist the new bar(s), then re-rank over all history.

        Returns the new standings, or ``None`` while there are too few bars to
        score (the bars are still persisted).
        """
        self.store.append_bars(self.id, bars_by_symbol)
        frames = self.store.load_frames(self.id)
        if not frames or min(len(f) for f in frames.values()) < 2:
            return None

        step = min(len(f) for f in frames.values())
        ts = max(pd.Timestamp(f.index[-1]) for f in frames.values()).isoformat()
        outcome = run_tournament(
            self.config.algo_paths, self.config.scenario(),
            metric=self.config.metric, isolation=self.config.isolation, frames=frames,
            harden=False,  # season uses fast thread isolation, which can't sandbox
        )
        standings = _standings_from_leaderboard(outcome.leaderboard)
        self.store.record_standings(self.id, step, ts, standings)
        self.store.set_status(self.id, "running")
        return StandingsSnapshot(step=step, total_steps=step, timestamp=ts, standings=standings)


# --------------------------------------------------------------------------- #
# Feeds — one bar per symbol per tick.
# --------------------------------------------------------------------------- #
class ReplaySeasonFeed:
    """Replays pre-built frames one bar at a time (offline / tests / demo)."""

    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self._frames = frames
        self._cursor = 0
        self._max = min(len(f) for f in frames.values()) if frames else 0

    def next(self) -> dict[str, pd.DataFrame] | None:
        if self._cursor >= self._max:
            return None
        bar = {s: f.iloc[[self._cursor]] for s, f in self._frames.items()}
        self._cursor += 1
        return bar


class AlpacaSeasonFeed:
    """Live one-bar-per-poll feed (lazy Alpaca; not exercised by the test suite)."""

    def __init__(self, symbols, timeframe: str, api_key: str, api_secret: str,
                 feed: str = "iex") -> None:
        from ..data.alpaca_data import AlpacaData

        self._symbols = list(symbols)
        self._timeframe = timeframe
        self._data = AlpacaData(api_key, api_secret, feed=feed)
        self._last_ts: dict[str, pd.Timestamp] = {}

    def next(self) -> dict[str, pd.DataFrame] | None:
        bar: dict[str, pd.DataFrame] = {}
        for symbol in self._symbols:
            df = self._data.history(symbol, timeframe=self._timeframe, lookback=5)
            if df.empty:
                continue
            last = df.iloc[[-1]]
            ts = pd.Timestamp(last.index[-1])
            if self._last_ts.get(symbol) == ts:
                continue  # no new bar yet
            self._last_ts[symbol] = ts
            bar[symbol] = last
        return bar or None


def run_season(season: Season, feed, max_ticks: int | None = None,
               poll_seconds: float = 0.0, pace_s: float = 0.0,
               stop_on_empty: bool = True, on_step=None,
               supervise: bool = False, on_error=None) -> int:
    """Drive a season from a feed. Returns the number of ticks applied.

    ``stop_on_empty=True`` (replay) stops when the feed is exhausted;
    ``stop_on_empty=False`` (live) waits ``poll_seconds`` for the next bar.
    With ``supervise=True`` a failing tick is caught (``on_error(exc)``) and the
    loop continues instead of crashing the run.
    """
    ticks = 0
    while max_ticks is None or ticks < max_ticks:
        bar = feed.next()
        if bar is None:
            if stop_on_empty:
                break
            if poll_seconds:
                time.sleep(poll_seconds)
                continue
            break
        try:
            snapshot = season.step(bar)
        except Exception as exc:  # noqa: BLE001 - daemon survives a bad tick
            if not supervise:
                raise
            if on_error is not None:
                on_error(exc)
            snapshot = None
        ticks += 1
        if snapshot is not None and on_step is not None:
            on_step(snapshot)
        if pace_s:
            time.sleep(pace_s)
    return ticks


def run_season_daemon(season: Season, feed, poll_seconds: float = 60.0,
                      ignore_market_hours: bool = False, max_ticks: int | None = None,
                      on_step=None, on_error=None, clock=None, sleep=None,
                      stop_on_empty: bool = False) -> int:
    """Daemon loop: gate on US market hours, drop still-forming bars, step under
    supervision. Returns the number of ticks applied.

    ``clock`` (-> tz-aware now) and ``sleep`` are injected so the *whole* loop is
    testable/runnable offline — pass a simulated clock + no-op sleep + a replay
    feed (that's what ``season run --simulate`` does). ``stop_on_empty`` ends the
    run when a (replay) feed is exhausted instead of polling forever.
    """
    from datetime import datetime, timezone

    from .market import drop_incomplete_bars, is_market_open

    if clock is None:
        clock = lambda: datetime.now(timezone.utc)  # noqa: E731
    if sleep is None:
        sleep = time.sleep

    ticks = 0
    while max_ticks is None or ticks < max_ticks:
        now = clock()
        if not ignore_market_hours and not is_market_open(now):
            sleep(poll_seconds)
            continue
        bar = feed.next()
        if bar is None:
            if stop_on_empty:
                break
            sleep(poll_seconds)
            continue
        bar = {s: drop_incomplete_bars(df, season.config.timeframe, now)
               for s, df in bar.items()}
        bar = {s: df for s, df in bar.items() if df is not None and len(df) > 0}
        if not bar:
            sleep(poll_seconds)
            continue
        try:
            snapshot = season.step(bar)
            if snapshot is not None and on_step is not None:
                on_step(snapshot)
        except Exception as exc:  # noqa: BLE001
            if on_error is not None:
                on_error(exc)
        ticks += 1
        sleep(poll_seconds)
    return ticks
