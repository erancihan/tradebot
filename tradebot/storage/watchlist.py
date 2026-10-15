"""Watchlist: the symbols the owner picked on the Today page.

When it is not empty, the advisor refresh, the web autopilot and ``tradebot
run`` all trade these instead of the config's ``symbols``: ``resolve_active``
is the one resolver. Symbols are stored validated and upper-case, in
insertion order.
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


def resolve_active(settings, store) -> dict:
    """``{symbols, source}``: the watchlist when it has any, else the config.

    ``store`` is anything with ``watchlist()``: the read-only web repository
    or a ``Storage``.
    """
    watched = store.watchlist()
    if watched:
        return {"symbols": watched, "source": "watchlist"}
    return {"symbols": list(settings.symbols), "source": "config"}


def active_symbols(settings, store) -> list[str]:
    """The active list: what Today suggests over and every loop trades."""
    return resolve_active(settings, store)["symbols"]
