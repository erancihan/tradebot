"""Read-only access to saved arena tournaments."""

from __future__ import annotations

import json

from ._db import _read


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
