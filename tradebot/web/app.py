"""FastAPI application factory."""

from __future__ import annotations

import logging
import mimetypes
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from ..autopilot.links import UsedLinks, link_secret
from ..config import Settings
from .access import AccessToken
from .guard import SameOriginGuard
from .routes import api, pages, partials, sse
from .services import autopilot_service
from .services.jobs import JobRegistry
from .startup import startup_line

# Not every platform's mimetypes table knows the PWA manifest extension, and a
# text/plain manifest is ignored by some browsers.
mimetypes.add_type("application/manifest+json", ".webmanifest")


log = logging.getLogger(__name__)

#: Host headers served by default. Anything else is refused, which is what
#: defeats DNS rebinding: a hostile page that re-points its own name at
#: 127.0.0.1 still sends its own name as the Host. Tests talk to localhost
#: rather than adding Starlette's ``testserver`` here.
DEFAULT_ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]

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


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # The autopilot loop is a thread inside this process: resume it if the
    # user left it on, and stop it with the server so no pass outlives it
    # (uvicorn turns SIGTERM from a service manager into this shutdown).
    log.info(startup_line(app))
    autopilot_service.resume(app)
    yield
    autopilot_service.shutdown(app)


def create_app(trading_db: str = "tradebot.db", arena_db: str = "arena.db",
               season_db: str = "season.db", cache_dir: str = "data/cache",
               settings_path: str | None = None,
               allowed_hosts: list[str] | None = None,
               access_token: str | None = None) -> FastAPI:
    app = FastAPI(title="tradebot dashboard", docs_url="/api/docs", lifespan=_lifespan)
    app.state.settings, app.state.settings_path = load_settings(settings_path)
    app.state.trading_db = trading_db
    app.state.arena_db = arena_db
    app.state.season_db = season_db
    app.state.cache_dir = cache_dir
    app.state.jobs = JobRegistry()
    app.state.allowed_hosts = list(DEFAULT_ALLOWED_HOSTS if allowed_hosts is None
                                   else allowed_hosts)
    app.state.token_required = bool(access_token)
    # Signs the phone push's Approve/Skip links: from the token, else random
    # for this process (links then die with a restart, as the batch does).
    app.state.link_secret = link_secret(access_token)
    app.state.used_links = UsedLinks()          # each link acts once

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
    _install_middleware(app, access_token)
    return app


def _install_middleware(app: FastAPI, access_token: str | None) -> None:
    """Starlette runs the LAST middleware added FIRST, so add innermost first.

    Request order: trusted host -> access token -> same-origin guard -> routes.
    A foreign Host is refused before anything else looks at it, and an
    unauthenticated caller learns nothing about which routes exist.
    """
    app.add_middleware(SameOriginGuard)
    if access_token:
        app.add_middleware(AccessToken, token=access_token)
    hosts = app.state.allowed_hosts
    if "*" in hosts:
        log.warning("Host checking is disabled (--allow-host '*'): the dashboard "
                    "is open to DNS-rebinding attacks from any web page")
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)
