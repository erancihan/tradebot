"""SQLite schema for the trading store (created on open, additive only)."""

from __future__ import annotations

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
