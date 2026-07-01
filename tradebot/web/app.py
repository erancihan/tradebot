"""FastAPI application factory."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .routes import api, pages, partials, sse
from .services.jobs_service import JobRegistry


def create_app(trading_db: str = "tradebot.db", arena_db: str = "arena.db",
               season_db: str = "season.db") -> FastAPI:
    app = FastAPI(title="tradebot dashboard", docs_url="/api/docs")
    app.state.trading_db = trading_db
    app.state.arena_db = arena_db
    app.state.season_db = season_db
    app.state.jobs = JobRegistry()

    static_dir = Path(__file__).parent / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    app.include_router(pages.router)
    app.include_router(partials.router)
    app.include_router(api.router)
    app.include_router(sse.router)
    return app
