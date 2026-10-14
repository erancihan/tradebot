"""Shared read-only SQLite helper for the dashboard repositories."""

from __future__ import annotations

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
