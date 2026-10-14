"""SQLite schema for a season: its config, accumulated bars and standings."""

from __future__ import annotations

_SCHEMA = """
CREATE TABLE IF NOT EXISTS seasons (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    symbols     TEXT NOT NULL,
    timeframe   TEXT NOT NULL,
    metric      TEXT NOT NULL,
    config_json TEXT NOT NULL,
    status      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS season_bars (
    season_id INTEGER NOT NULL,
    symbol    TEXT NOT NULL,
    ts        TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL, volume REAL,
    PRIMARY KEY (season_id, symbol, ts)
);
CREATE TABLE IF NOT EXISTS season_standings (
    season_id      INTEGER NOT NULL,
    step           INTEGER NOT NULL,
    ts             TEXT NOT NULL,
    standings_json TEXT NOT NULL,
    PRIMARY KEY (season_id, step)
);
"""
