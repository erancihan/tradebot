"""Read-only access to the bot's SQLite logs.

Both repositories tolerate a missing database or missing tables (returning empty
results) so the dashboard renders cleanly before the bot has ever run. Databases
are opened read-only so the web layer can never mutate trading data.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path


def _read(db_path: str, sql: str, params: tuple = ()) -> list[dict]:
    if not Path(db_path).exists():
        return []
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]
        finally:
            conn.close()
    except sqlite3.OperationalError:
        return []  # table doesn't exist yet


class TradingRepository:
    """Equity snapshots + orders written by the engine / dry-run / arena."""

    def __init__(self, db_path: str = "tradebot.db") -> None:
        self.db_path = db_path

    def equity_series(self, mode: str | None = None, limit: int = 2000) -> list[dict]:
        where = "WHERE mode = ?" if mode else ""
        params = (mode, limit) if mode else (limit,)
        rows = _read(
            self.db_path,
            f"SELECT ts, equity, cash, mode FROM equity_snapshots {where} "
            "ORDER BY id DESC LIMIT ?",
            params,
        )
        rows.reverse()  # chronological for charting
        return rows

    def recent_orders(self, limit: int = 50, mode: str | None = None) -> list[dict]:
        where = "WHERE mode = ?" if mode else ""
        params = (mode, limit) if mode else (limit,)
        return _read(
            self.db_path,
            f"SELECT ts, symbol, side, qty, type, broker_order_id, mode FROM orders "
            f"{where} ORDER BY id DESC LIMIT ?",
            params,
        )

    def modes(self) -> list[str]:
        rows = _read(self.db_path, "SELECT DISTINCT mode FROM equity_snapshots ORDER BY mode")
        return [r["mode"] for r in rows]

    def symbols(self) -> list[str]:
        rows = _read(self.db_path, "SELECT DISTINCT symbol FROM bars ORDER BY symbol")
        return [r["symbol"] for r in rows]

    def bars(self, symbol: str, mode: str | None = None, limit: int = 500) -> list[dict]:
        where = "WHERE symbol = ?" + (" AND mode = ?" if mode else "")
        params = (symbol, mode, limit) if mode else (symbol, limit)
        rows = _read(
            self.db_path,
            f"SELECT ts, open, high, low, close, volume FROM bars {where} "
            "ORDER BY ts DESC LIMIT ?",
            params,
        )
        rows.reverse()  # chronological for charting
        return rows

    def latest_equity(self) -> dict | None:
        rows = _read(
            self.db_path,
            "SELECT ts, equity, cash, mode FROM equity_snapshots ORDER BY id DESC LIMIT 1",
        )
        return rows[0] if rows else None


class ArenaRepository:
    """Saved tournaments (runs, results, equity curves)."""

    def __init__(self, db_path: str = "arena.db") -> None:
        self.db_path = db_path

    def list_runs(self) -> list[dict]:
        return _read(
            self.db_path,
            "SELECT r.*, (SELECT name FROM arena_results WHERE run_id = r.id AND rank = 1)"
            " AS winner FROM arena_runs r ORDER BY r.id DESC",
        )

    def get_run(self, run_id: int) -> dict | None:
        run = _read(self.db_path, "SELECT * FROM arena_runs WHERE id = ?", (run_id,))
        if not run:
            return None
        results = _read(
            self.db_path,
            "SELECT * FROM arena_results WHERE run_id = ? ORDER BY (rank IS NULL), rank",
            (run_id,),
        )
        return {"run": run[0], "results": results}

    def latest_run_id(self) -> int | None:
        runs = self.list_runs()
        return runs[0]["id"] if runs else None

    @staticmethod
    def parse_equity(equity_json: str | None) -> dict | None:
        if not equity_json:
            return None
        try:
            return json.loads(equity_json)
        except (json.JSONDecodeError, TypeError):
            return None


class SeasonRepository:
    """Read-only access to a live-league season DB (season.db)."""

    def __init__(self, db_path: str = "season.db") -> None:
        self.db_path = db_path

    def list_seasons(self) -> list[dict]:
        return _read(
            self.db_path,
            "SELECT id, name, symbols, timeframe, metric, status, updated_at "
            "FROM seasons ORDER BY id DESC",
        )

    def get_season(self, season_id: int) -> dict | None:
        rows = _read(
            self.db_path,
            "SELECT id, name, symbols, timeframe, metric, status, updated_at "
            "FROM seasons WHERE id = ?", (season_id,),
        )
        return rows[0] if rows else None

    def latest_standings(self, season_id: int) -> list[dict]:
        rows = _read(
            self.db_path,
            "SELECT standings_json FROM season_standings WHERE season_id = ? "
            "ORDER BY step DESC LIMIT 1", (season_id,),
        )
        return json.loads(rows[0]["standings_json"]) if rows else []

    def standings_history(self, season_id: int) -> list[dict]:
        rows = _read(
            self.db_path,
            "SELECT step, ts, standings_json FROM season_standings "
            "WHERE season_id = ? ORDER BY step", (season_id,),
        )
        return [
            {"step": r["step"], "ts": r["ts"], "standings": json.loads(r["standings_json"])}
            for r in rows
        ]
