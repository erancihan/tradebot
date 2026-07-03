"""Lightweight SQLite persistence (stdlib only).

Records orders the bot submits and periodic equity snapshots, so a crash or
restart leaves an auditable trail and you can chart performance over time.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from .models import Order, utcnow


def _ts_iso(ts) -> str:
    """Normalise a bar timestamp (pandas Timestamp / datetime / str) to ISO text."""
    iso = getattr(ts, "isoformat", None)
    return iso() if callable(iso) else str(ts)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    side            TEXT NOT NULL,
    qty             REAL NOT NULL,
    type            TEXT NOT NULL,
    broker_order_id TEXT,
    mode            TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS equity_snapshots (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      TEXT NOT NULL,
    equity  REAL NOT NULL,
    cash    REAL NOT NULL,
    mode    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS bars (
    symbol     TEXT NOT NULL,
    timeframe  TEXT NOT NULL,
    ts         TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL, volume REAL,
    mode       TEXT NOT NULL,
    PRIMARY KEY (symbol, timeframe, ts, mode)
);
CREATE TABLE IF NOT EXISTS target_weights (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      TEXT NOT NULL,
    symbol  TEXT NOT NULL,
    weight  REAL NOT NULL,
    mode    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS universe_snapshots (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      TEXT NOT NULL,
    symbols TEXT NOT NULL,      -- JSON array, point-in-time candidate list
    mode    TEXT NOT NULL
);
"""


class Storage:
    def __init__(self, path: str | Path = "tradebot.db") -> None:
        self.path = str(path)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        with closing(self._conn.cursor()) as cur:
            cur.executescript(_SCHEMA)
        self._conn.commit()

    def record_order(self, order: Order, broker_order_id: str | None, mode: str) -> None:
        self._conn.execute(
            "INSERT INTO orders (ts, symbol, side, qty, type, broker_order_id, mode)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                order.created_at.isoformat(),
                order.symbol,
                order.side.value,
                order.qty,
                order.type.value,
                broker_order_id,
                mode,
            ),
        )
        self._conn.commit()

    def record_bars(self, symbol: str, timeframe: str, bars, mode: str) -> None:
        """Persist OHLCV bars (idempotent — duplicate timestamps are ignored)."""
        rows = [
            (symbol, timeframe, _ts_iso(ts), float(r["open"]), float(r["high"]),
             float(r["low"]), float(r["close"]), float(r["volume"]), mode)
            for ts, r in bars.iterrows()
        ]
        if not rows:
            return
        self._conn.executemany(
            "INSERT OR IGNORE INTO bars"
            " (symbol, timeframe, ts, open, high, low, close, volume, mode)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        self._conn.commit()

    def record_weights(self, weights: dict[str, float], mode: str) -> None:
        """Persist the allocator's target weights for one rebalance pass."""
        if not weights:
            return
        ts = utcnow().isoformat()
        self._conn.executemany(
            "INSERT INTO target_weights (ts, symbol, weight, mode) VALUES (?, ?, ?, ?)",
            [(ts, sym, float(w), mode) for sym, w in weights.items()],
        )
        self._conn.commit()

    def latest_weights(self, mode: str | None = None) -> dict[str, float]:
        """The most recent rebalance's target weights (optionally per mode)."""
        where = "WHERE mode = ?" if mode else ""
        args = (mode,) if mode else ()
        row = self._conn.execute(
            f"SELECT ts FROM target_weights {where} ORDER BY ts DESC, id DESC LIMIT 1",
            args,
        ).fetchone()
        if row is None:
            return {}
        rows = self._conn.execute(
            f"SELECT symbol, weight FROM target_weights {where}"
            f"{' AND' if mode else ' WHERE'} ts = ?",
            args + (row["ts"],),
        ).fetchall()
        return {r["symbol"]: r["weight"] for r in rows}

    def record_universe(self, symbols: list[str], mode: str) -> None:
        """Persist a resolved candidate universe (point-in-time paper trail)."""
        import json

        if not symbols:
            return
        self._conn.execute(
            "INSERT INTO universe_snapshots (ts, symbols, mode) VALUES (?, ?, ?)",
            (utcnow().isoformat(), json.dumps(list(symbols)), mode),
        )
        self._conn.commit()

    def latest_universe(self, mode: str | None = None) -> list[str]:
        """The most recently resolved universe (optionally per mode)."""
        import json

        where = "WHERE mode = ?" if mode else ""
        args = (mode,) if mode else ()
        row = self._conn.execute(
            f"SELECT symbols FROM universe_snapshots {where} ORDER BY id DESC LIMIT 1",
            args,
        ).fetchone()
        return json.loads(row["symbols"]) if row else []

    def record_equity(self, equity: float, cash: float, mode: str) -> None:
        self._conn.execute(
            "INSERT INTO equity_snapshots (ts, equity, cash, mode) VALUES (?, ?, ?, ?)",
            (utcnow().isoformat(), equity, cash, mode),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Storage":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
