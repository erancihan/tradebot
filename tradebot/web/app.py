"""FastAPI application factory."""

from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .routes import api, pages, partials, sse
from .services.jobs import JobRegistry

# Not every platform's mimetypes table knows the PWA manifest extension, and a
# text/plain manifest is ignored by some browsers.
mimetypes.add_type("application/manifest+json", ".webmanifest")


def create_app(trading_db: str = "tradebot.db", arena_db: str = "arena.db",
               season_db: str = "season.db", cache_dir: str = "data/cache") -> FastAPI:
    app = FastAPI(title="tradebot dashboard", docs_url="/api/docs")
    app.state.trading_db = trading_db
    app.state.arena_db = arena_db
    app.state.season_db = season_db
    app.state.cache_dir = cache_dir
    app.state.jobs = JobRegistry()

    static_dir = Path(__file__).parent / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    # Hand-written, committed assets (PWA manifest + icons). Kept apart from
    # /static, which is a gitignored build output that `npm run build` rewrites.
    app_assets = Path(__file__).parent / "static-src"
    app.mount("/app", StaticFiles(directory=str(app_assets)), name="app-assets")

    app.include_router(pages.router)
    app.include_router(partials.router)
    app.include_router(api.router)
    app.include_router(sse.router)
    return app
