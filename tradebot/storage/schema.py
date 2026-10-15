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
CREATE TABLE IF NOT EXISTS proposal_batches (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT NOT NULL,
    mode        TEXT NOT NULL,
    equity      REAL NOT NULL,
    cash        REAL NOT NULL,
    provenance  TEXT NOT NULL       -- JSON: data source, bars, window, account
);
CREATE TABLE IF NOT EXISTS proposals (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id     INTEGER NOT NULL REFERENCES proposal_batches(id),
    created_at   TEXT NOT NULL,
    mode         TEXT NOT NULL,
    symbol       TEXT NOT NULL,
    action       TEXT NOT NULL,     -- buy | sell | hold
    target       INTEGER NOT NULL,
    current_qty  REAL NOT NULL,
    desired_qty  REAL NOT NULL,
    order_qty    REAL NOT NULL,
    price        REAL NOT NULL,
    notional     REAL NOT NULL,
    weight       REAL,
    reason       TEXT NOT NULL,
    status       TEXT NOT NULL      -- suggested | pending | approved | rejected | submitted
);
CREATE INDEX IF NOT EXISTS proposals_batch ON proposals (batch_id);
CREATE TABLE IF NOT EXISTS autopilot_state (
    scope  TEXT NOT NULL,       -- the engine's mode label: paper | dry_run
    key    TEXT NOT NULL,       -- mode | started_at | last_pass_at | next_pass_at | last_error
    value  TEXT,
    PRIMARY KEY (scope, key)
);
CREATE TABLE IF NOT EXISTS watchlist (
    symbol    TEXT PRIMARY KEY,     -- upper-case, validated by the web layer
    added_at  TEXT NOT NULL
);
"""
