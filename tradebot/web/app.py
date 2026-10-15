"""FastAPI application factory."""

from __future__ import annotations

import logging
import mimetypes
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from ..autopilot.links import UsedLinks, link_secret
from ..config import DEFAULT_SYMBOLS, Settings, resolve_settings  # noqa: F401 - re-exported
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


def load_settings(settings_path: str | None) -> tuple[Settings, str | None]:
    """The server's trading settings and their file (None = defaults); see ``resolve_settings``."""
    return resolve_settings(settings_path)


#: Names the trading database when no ``trading_db`` is passed (``--trading-db``).
DB_ENV = "TRADEBOT_DB"


def trading_db_path(explicit: str | None, settings: Settings) -> str:
    """``explicit`` (``--trading-db``), else ``$TRADEBOT_DB``, else the config's
    ``db_path``: the file ``tradebot run`` writes, so the CLI and the web on
    one machine share one database unless told otherwise."""
    return explicit or os.environ.get(DB_ENV) or settings.db_path


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # The autopilot loop is a thread inside this process: resume it if the
    # user left it on, and stop it with the server so no pass outlives it
    # (uvicorn turns SIGTERM from a service manager into this shutdown).
    log.info(startup_line(app))
    autopilot_service.resume(app)
    yield
    autopilot_service.shutdown(app)


def create_app(trading_db: str | None = None, arena_db: str = "arena.db",
               season_db: str = "season.db", cache_dir: str = "data/cache",
               settings_path: str | None = None,
               allowed_hosts: list[str] | None = None,
               access_token: str | None = None) -> FastAPI:
    app = FastAPI(title="tradebot dashboard", docs_url="/api/docs", lifespan=_lifespan)
    app.state.settings, app.state.settings_path = load_settings(settings_path)
    app.state.trading_db = trading_db_path(trading_db, app.state.settings)
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
