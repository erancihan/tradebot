"""Discover runs: the last "what else could I buy?" ranking, kept across restarts.

One row per run. ``rows`` is the ranked list as JSON and ``provenance`` the
record of what it ran on, so the Today page can show the newest run after a
restart without recomputing it. A run suggests names only; nothing here trades.
"""

from __future__ import annotations

import json

from ..models import utcnow


class DiscoverMixin:
    """Discover run reads and writes over ``self._conn``."""

    def record_discover_run(self, *, source: str, as_of: str | None,
                            provenance: dict, rows: list[dict]) -> int:
        cur = self._conn.execute(
            "INSERT INTO discover_runs (created_at, source, as_of, provenance, rows) "
            "VALUES (?, ?, ?, ?, ?)",
            (utcnow().isoformat(), source, as_of, json.dumps(provenance),
             json.dumps(rows)))
        self._conn.commit()
        return int(cur.lastrowid)

    def latest_discover_run(self) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM discover_runs ORDER BY id DESC LIMIT 1").fetchone()
        return decode_run(dict(row)) if row else None


def decode_run(row: dict) -> dict:
    """A stored run with its JSON columns parsed (shared with the web repository)."""
    out = dict(row)
    for key, empty in (("provenance", {}), ("rows", [])):
        try:
            out[key] = json.loads(out.get(key) or "null") or empty
        except (json.JSONDecodeError, TypeError):
            out[key] = empty
    return out
