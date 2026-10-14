"""Read-only access to the bot's SQLite logs.

Both repositories tolerate a missing database or missing tables (returning empty
results) so the dashboard renders cleanly before the bot has ever run. Databases
are opened read-only so the web layer can never mutate trading data.
"""

from __future__ import annotations

from .arena import ArenaRepository
from .season import SeasonRepository
from .trading import TradingRepository

__all__ = ["ArenaRepository", "SeasonRepository", "TradingRepository"]
