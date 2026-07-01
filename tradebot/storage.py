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
