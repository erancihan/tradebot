"""Lightweight SQLite persistence (stdlib only).

Records orders the bot submits and periodic equity snapshots, so a crash or
restart leaves an auditable trail and you can chart performance over time.
"""

from __future__ import annotations
import sqlite3
from contextlib import closing
from pathlib import Path

from .autopilot import AutopilotMixin
from .bars import BarsMixin, _ts_iso
from .orders import OrdersMixin
from .proposals import ProposalsMixin
from .schema import _SCHEMA
from .watchlist import WatchlistMixin
from .weights import WeightsMixin

__all__ = ["Storage"]


class Storage(OrdersMixin, BarsMixin, WeightsMixin, ProposalsMixin, AutopilotMixin,
              WatchlistMixin):
    def __init__(self, path: str | Path = "tradebot.db", *,
                 check_same_thread: bool = True) -> None:
        # ``check_same_thread=False`` is for the autopilot, whose loop thread
        # and the web request threads share one connection; the autopilot
        # serialises every use behind its own lock.
        self.path = str(path)
        self._conn = sqlite3.connect(self.path, check_same_thread=check_same_thread)
        self._conn.row_factory = sqlite3.Row
        with closing(self._conn.cursor()) as cur:
            cur.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Storage":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
