"""FastAPI application factory."""

from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from ..config import Settings
from .routes import api, pages, partials, sse
from .services.jobs import JobRegistry

# Not every platform's mimetypes table knows the PWA manifest extension, and a
# text/plain manifest is ignored by some browsers.
mimetypes.add_type("application/manifest+json", ".webmanifest")


#: What the Today page advises on when no config file exists: a broad market
#: pair, so a fresh install has something meaningful to show.
DEFAULT_SYMBOLS = ["SPY", "QQQ"]


def load_settings(settings_path: str | None) -> tuple[Settings, str | None]:
    """The server's trading settings and the file they came from (None = defaults).

    An explicit path must exist; the implicit ``config.yaml`` in the working
    directory is used only when present, so the dashboard runs without one.
    """
    if settings_path is None and Path("config.yaml").exists():
        settings_path = "config.yaml"
    if settings_path is None:
        return Settings(symbols=list(DEFAULT_SYMBOLS)), None
    return Settings.from_yaml(settings_path), str(settings_path)


def create_app(trading_db: str = "tradebot.db", arena_db: str = "arena.db",
               season_db: str = "season.db", cache_dir: str = "data/cache",
               settings_path: str | None = None) -> FastAPI:
    app = FastAPI(title="tradebot dashboard", docs_url="/api/docs")
    app.state.settings, app.state.settings_path = load_settings(settings_path)
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
