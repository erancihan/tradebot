"""Real-time league with a durable, resumable *season*.

A season runs the field over wall-clock time: on each tick a new bar arrives,
gets appended to the season's shared bar history (persisted to SQLite), and the
field is re-ranked over everything seen so far. The standings are recorded each
tick, so the season survives restarts — reload it and keep stepping.

Design (reuse-heavy, drift-free):
- The **bars are the source of truth.** Standings are recomputed each tick by
  ``run_tournament`` over the accumulated frames (each contestant is
  look-ahead-safe and deterministic, so re-ranking the full history is exactly
  what a true streamed run would have shown — no per-contestant state to persist
  or risk corrupting). Recompute is O(history) per tick, fine for daily cadence.
- The **feed** is abstracted: ``ReplaySeasonFeed`` drives it offline/in tests;
  an Alpaca-backed feed (lazy) drives it live. ``Season.step`` only ever sees a
  dict of one-bar-per-symbol, so the engine is fully testable without a network.

``run_season`` is the thin loop (one tick per bar, no scheduling).
``run_season_daemon`` is the operational one: it gates on US market hours and
the holiday calendar, drops still-forming bars, supervises failing ticks, and
takes an injected ``clock``/``sleep`` so the whole loop is runnable offline —
which is what ``season run --simulate`` does.
"""

from __future__ import annotations

from .config import SeasonConfig
from .daemon import run_season, run_season_daemon
from .feeds import AlpacaSeasonFeed, ReplaySeasonFeed, StreamSeasonFeed
from .model import Season, _standings_from_leaderboard, seed_season
from .schema import _SCHEMA
from .store import SeasonStore

__all__ = [
    "AlpacaSeasonFeed", "ReplaySeasonFeed", "Season", "SeasonConfig", "SeasonStore",
    "StreamSeasonFeed", "run_season", "run_season_daemon", "seed_season",
]
