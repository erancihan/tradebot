"""Watchlist: the symbols the owner picked on the Today page.

When it is not empty, the advisor refresh and the web autopilot scan these
instead of the config's ``symbols`` (``web/services/symbols_service.py``).
Symbols are stored already validated and upper-case; order is insertion.
"""

from __future__ import annotations

from ..models import utcnow


class WatchlistMixin:
    """Watchlist reads and writes over ``self._conn``."""

    def watchlist(self) -> list[str]:
        rows = self._conn.execute(
            "SELECT symbol FROM watchlist ORDER BY rowid").fetchall()
        return [r["symbol"] for r in rows]

    def add_to_watchlist(self, symbols: list[str]) -> None:
        # INSERT OR IGNORE: re-adding a symbol keeps its original place.
        ts = utcnow().isoformat()
        self._conn.executemany(
            "INSERT OR IGNORE INTO watchlist (symbol, added_at) VALUES (?, ?)",
            [(s, ts) for s in symbols])
        self._conn.commit()

    def remove_from_watchlist(self, symbols: list[str]) -> None:
        self._conn.executemany("DELETE FROM watchlist WHERE symbol = ?",
                               [(s,) for s in symbols])
        self._conn.commit()
