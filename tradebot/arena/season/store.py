"""SQLite persistence for seasons: bars are the source of truth."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pandas as pd

from ...models import BAR_COLUMNS, utcnow
from ..league import Standing, StandingsSnapshot
from .config import SeasonConfig
from .schema import _SCHEMA


class SeasonStore:
    def __init__(self, path: str | Path = "season.db") -> None:
        self.path = str(path)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        with closing(self._conn.cursor()) as cur:
            cur.executescript(_SCHEMA)
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        """Additive columns only, so an older season DB keeps working."""
        cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(seasons)")}
        if "seeded_through" not in cols:
            self._conn.execute("ALTER TABLE seasons ADD COLUMN seeded_through TEXT")

    def set_seeded_through(self, season_id: int, ts: str) -> None:
        """Mark where backfilled history ends and live accumulation begins.

        Seeding is legitimate — bars are bars, and every contestant is causal, so
        replaying real history is exactly what running the season over that
        period would have produced. But standings earned over backfilled bars are
        NOT the same claim as standings earned live: the window was chosen after
        the fact, and everything in it was knowable when the field was written.
        Recording the boundary is what keeps those two claims separable.
        """
        self._conn.execute("UPDATE seasons SET seeded_through = ? WHERE id = ?",
                           (ts, season_id))
        self._conn.commit()

    def seeded_through(self, season_id: int) -> str | None:
        row = self._conn.execute(
            "SELECT seeded_through FROM seasons WHERE id = ?", (season_id,)).fetchone()
        return row["seeded_through"] if row else None

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
            time_budget_s=extra.get("time_budget_s", 10.0),
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
