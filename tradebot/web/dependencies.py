"""Shared dependencies: the Jinja environment and per-request repositories.

Repositories are constructed from paths held on ``app.state`` so tests can point
the app at temporary databases.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

from .repository import ArenaRepository, SeasonRepository, TradingRepository

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _pct(value) -> str:
    return "—" if value is None else f"{value * 100:.2f}%"


def _money(value) -> str:
    return "—" if value is None else f"${value:,.2f}"


templates.env.filters["pct"] = _pct
templates.env.filters["money"] = _money


def get_trading_repo(request: Request) -> TradingRepository:
    return TradingRepository(request.app.state.trading_db)


def get_arena_repo(request: Request) -> ArenaRepository:
    return ArenaRepository(request.app.state.arena_db)


def get_season_repo(request: Request) -> SeasonRepository:
    return SeasonRepository(request.app.state.season_db)
