"""SQLite persistence for tournaments.

Each run records its metadata, every contestant's outcome, and the equity curve
(as JSON) so a past tournament can be re-listed, re-printed, or charted later by
the dashboard. Stdlib ``sqlite3`` only — no migrations, schema is created on open.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from math import isfinite, nan
from pathlib import Path

from ..models import utcnow
from .result import render_table

#: Identifies the *instrument* that produced a journalled number, so results
#: from before and after a correctness fix are never silently compared. Bump it
#: whenever a change alters what the execution loops compute. History:
#:   e1  original loops
#:   e2  2026-07-25 — sizing marked at the fill bar's open, not its close
#:                    (`backtest._sizing_marks`); targets computed after
#:                    alignment; `exit_rank` no longer freezes on small pools.
ENGINE_VERSION = "e2"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS arena_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT NOT NULL,
    scenario        TEXT NOT NULL,
    metric          TEXT NOT NULL,
    symbols         TEXT NOT NULL,
    num_contestants INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS arena_results (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        INTEGER NOT NULL REFERENCES arena_runs(id),
    rank          INTEGER,
    name          TEXT NOT NULL,
    author        TEXT,
    kind          TEXT,
    status        TEXT NOT NULL,
    score         REAL,
    total_return  REAL,
    sharpe        REAL,
    max_drawdown  REAL,
    num_trades    INTEGER,
    error         TEXT,
    equity_json   TEXT
);
CREATE INDEX IF NOT EXISTS idx_results_run ON arena_results(run_id);
CREATE TABLE IF NOT EXISTS experiments (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            TEXT NOT NULL,
    family        TEXT NOT NULL,
    name          TEXT NOT NULL,
    scenario      TEXT NOT NULL,
    metric        TEXT NOT NULL,
    score         REAL,
    status        TEXT NOT NULL,
    start_balance REAL,       -- scores rank; balances tell the money story
    final_balance REAL,
    start_date    TEXT,       -- simulated data window (first/last bar)
    end_date      TEXT,
    run_id        INTEGER,    -- arena_runs.id when the run was --save'd
    engine        TEXT        -- instrument version; see ENGINE_VERSION
);
CREATE INDEX IF NOT EXISTS idx_experiments_family ON experiments(family);
"""


@dataclass
class StoredRow:
    """A reconstructed result row that ``render_table`` can format."""

    rank: int | None
    name: str
    author: str
    kind: str
    status: str
    score: float | None
    total_return: float
    sharpe: float
    max_drawdown: float
    num_trades: int
    error: str | None

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def _clean(value: float) -> float | None:
    """NaN/inf -> NULL so the DB stores clean numbers."""
    return value if value is not None and isfinite(value) else None


def equity_to_json(curve) -> str:
    return json.dumps(
        {
            "index": [ts.isoformat() for ts in curve.index],
            "equity": [float(v) for v in curve.to_numpy()],
        }
    )


class ArenaStore:
    def __init__(self, path: str | Path = "arena.db") -> None:
        self.path = str(path)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        with closing(self._conn.cursor()) as cur:
            cur.executescript(_SCHEMA)
        # Additive column migration for journals created before balances were
        # recorded (CREATE IF NOT EXISTS won't touch an existing table).
        cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(experiments)")}
        for col, kind in (("start_balance", "REAL"), ("final_balance", "REAL"),
                          ("start_date", "TEXT"), ("end_date", "TEXT"),
                          ("engine", "TEXT")):
            if col not in cols:
                self._conn.execute(f"ALTER TABLE experiments ADD COLUMN {col} {kind}")
        self._conn.commit()

    def record_run(self, scenario, metric: str, outcome) -> int:
        entries = outcome.leaderboard.entries
        cur = self._conn.execute(
            "INSERT INTO arena_runs (ts, scenario, metric, symbols, num_contestants)"
            " VALUES (?, ?, ?, ?, ?)",
            (utcnow().isoformat(), scenario.name, metric,
             ",".join(scenario.symbols), len(entries)),
        )
        run_id = cur.lastrowid
        for r in entries:
            equity = equity_to_json(r.result.equity_curve) if r.result is not None else None
            self._conn.execute(
                "INSERT INTO arena_results (run_id, rank, name, author, kind, status,"
                " score, total_return, sharpe, max_drawdown, num_trades, error, equity_json)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, r.rank, r.name, r.author, r.kind, r.status,
                 _clean(r.score), _clean(r.total_return), _clean(r.sharpe),
                 _clean(r.max_drawdown), r.num_trades, r.error, equity),
            )
        self._conn.commit()
        return run_id

    def record_attempts(self, scenario, metric: str, outcome, run_id: int | None = None,
                        only_families: set[str] | None = None) -> int:
        """Journal one experiment row per contestant (the data-snooping ledger).

        Every evaluation counts as an attempt — including failures. Attempts are
        grouped by the contestant's ``family`` (default: its name), so trying
        ten variants of one idea shows up as ten attempts against that idea.

        ``only_families`` restricts journaling to the ideas actually under
        development. The pass gate needs it: it runs the *whole* field against
        every gauntlet scenario merely to obtain a baseline, so journaling
        everyone charged +1 attempt per scenario to all twelve families. That is
        how `buy_and_hold` — never iterated on once — came to carry the same
        attempt count as a candidate under active development, and it made the
        multiple-testing statistic measure gate invocations rather than
        iterations of an idea.
        """
        ts = utcnow().isoformat()
        entries = outcome.leaderboard.entries
        if only_families is not None:
            entries = [r for r in entries
                       if (getattr(r.contestant, "family", "") or r.name) in only_families]
        for r in entries:
            family = getattr(r.contestant, "family", "") or r.name
            start = final = first = last = None
            if r.result is not None:
                start = float(r.result.initial_cash)
                final = float(r.result.final_equity)
                curve = r.result.equity_curve
                if len(curve):
                    first = str(curve.index[0])
                    last = str(curve.index[-1])
            self._conn.execute(
                "INSERT INTO experiments (ts, family, name, scenario, metric,"
                " score, status, start_balance, final_balance, start_date,"
                " end_date, run_id, engine)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (ts, family, r.name, scenario.name, metric, _clean(r.score),
                 r.status, _clean(start), _clean(final), first, last, run_id,
                 ENGINE_VERSION),
            )
        self._conn.commit()
        return len(entries)

    def journal_summary(self) -> list[dict]:
        """Attempts per family, most-tried first, with each family's best score."""
        rows = self._conn.execute(
            "SELECT family, COUNT(*) AS attempts, COUNT(DISTINCT name) AS variants,"
            " COUNT(DISTINCT scenario) AS scenarios, MAX(ts) AS last_ts"
            " FROM experiments GROUP BY family ORDER BY attempts DESC, family"
        ).fetchall()
        out = []
        for row in rows:
            best = self._conn.execute(
                "SELECT name, scenario, metric, score, start_balance,"
                " final_balance, start_date, end_date"
                " FROM experiments WHERE family = ? AND score IS NOT NULL"
                " ORDER BY score DESC LIMIT 1",
                (row["family"],),
            ).fetchone()
            d = dict(row)
            d["best"] = dict(best) if best else None
            out.append(d)
        return out

    def journal_entries(self, family: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM experiments WHERE family = ? ORDER BY id DESC",
            (family,),
        ).fetchall()
        return [dict(r) for r in rows]

    def list_runs(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT r.*, (SELECT name FROM arena_results WHERE run_id = r.id AND rank = 1)"
            " AS winner FROM arena_runs r ORDER BY r.id DESC"
        ).fetchall()
        return [dict(row) for row in rows]

    def get_run(self, run_id: int) -> dict | None:
        run = self._conn.execute(
            "SELECT * FROM arena_runs WHERE id = ?", (run_id,)
        ).fetchone()
        if run is None:
            return None
        results = self._conn.execute(
            "SELECT * FROM arena_results WHERE run_id = ?"
            " ORDER BY (rank IS NULL), rank", (run_id,)
        ).fetchall()
        return {"run": dict(run), "results": [dict(r) for r in results]}

    def latest_run_id(self) -> int | None:
        row = self._conn.execute("SELECT MAX(id) AS m FROM arena_runs").fetchone()
        return row["m"] if row and row["m"] is not None else None

    def render_run(self, run_id: int) -> str | None:
        data = self.get_run(run_id)
        if data is None:
            return None
        rows = [
            StoredRow(
                rank=r["rank"], name=r["name"], author=r["author"] or "",
                kind=r["kind"] or "", status=r["status"], score=r["score"],
                total_return=r["total_return"] if r["total_return"] is not None else nan,
                sharpe=r["sharpe"] if r["sharpe"] is not None else nan,
                max_drawdown=r["max_drawdown"] if r["max_drawdown"] is not None else nan,
                num_trades=r["num_trades"] or 0, error=r["error"],
            )
            for r in data["results"]
        ]
        return render_table(data["run"]["metric"], rows)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "ArenaStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
