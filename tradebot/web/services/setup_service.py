"""What a fresh install still lacks, and the one step that fixes each.

The Today page shows these as a card until all three are ready, so a phone
user is never told to run a command they have no terminal for unless there
is no other way (pulling bars without server keys is the one such case).
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from ...data.cache import BarCache
from . import symbols_service
from .jobs.frames import _pull_hint
from .settings_service import credentials_present

#: History a first pull asks for: enough for a 252-bar momentum lookback.
PULL_YEARS = 2


def setup_status(settings, settings_path: str | None, cache_dir: str, store,
                 today: date | None = None) -> dict:
    """``{config, credentials, bars}``, each ``{ok, hint}``; plus ``ready``.

    ``store`` is anything with ``watchlist()``: bars are checked for the
    symbols the Today refresh will actually scan.
    """
    creds = credentials_present()
    status = {
        "config": _config(settings_path),
        "credentials": {
            "ok": creds,
            "hint": None if creds else (
                "Add ALPACA_API_KEY and ALPACA_API_SECRET (free paper keys from "
                "alpaca.markets) to .env on the server and restart it. Until then "
                "the bot runs on cached bars only."),
        },
        "bars": _bars(settings, cache_dir, store, creds, today or date.today()),
    }
    status["ready"] = all(item["ok"] for item in status.values())
    return status


def _config(settings_path: str | None) -> dict:
    ok = settings_path is not None and Path(settings_path).exists()
    return {"ok": ok, "hint": None if ok else (
        "No config file yet: open Settings, pick your symbols and a strategy, and Save.")}


def _bars(settings, cache_dir: str, store, creds: bool, today: date) -> dict:
    cache, tf = BarCache(cache_dir), settings.timeframe
    symbols = symbols_service.active_symbols(settings, store)
    missing = [s for s in symbols if not cache.path(s, tf).exists()]
    if not missing:
        return {"ok": True, "hint": None, "missing": []}
    if creds:
        hint = "Tap Refresh: the server will fetch the missing price history."
    else:
        start = today - timedelta(days=365 * PULL_YEARS)
        hint = ("No price history cached for " + ", ".join(missing) + ". On the server, run: "
                + _pull_hint(" ".join(missing), tf, start.isoformat(), today.isoformat()))
    return {"ok": False, "hint": hint, "missing": missing}
