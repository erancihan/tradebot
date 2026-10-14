"""The Autopilot page's data and commands; owns the process's one Autopilot.

The account scope follows the server's credentials: with Alpaca keys the
autopilot trades the *paper* account ("paper"); without them it runs a
dry-run over the cached bars ("dry_run"). The web never reaches a live
account, so there is no mode here that could.

The Autopilot is built lazily on the first command that needs an engine, so
viewing the page never constructs a broker; until then the state is read
straight from SQLite.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone

from ...autopilot import MODE_LABELS, Autopilot, load_state, store_mode
from ...config import AlpacaCredentials
from ...storage import Storage
from . import autopilot_build

_BUILD_LOCK = threading.Lock()


class AutopilotUnavailable(RuntimeError):
    """The engine cannot be built (e.g. offline with nothing cached)."""


def scope() -> str:
    return "paper" if AlpacaCredentials.from_env() is not None else "dry_run"


def current(app) -> Autopilot | None:
    return getattr(app.state, "autopilot", None)


def get(app) -> Autopilot:
    """The process's Autopilot, built on first use."""
    with _BUILD_LOCK:
        pilot = current(app)
        if pilot is None:
            state = app.state
            try:
                pilot = autopilot_build.build(state.settings, trading_db=state.trading_db,
                                              cache_dir=state.cache_dir)
            except RuntimeError as exc:
                raise AutopilotUnavailable(str(exc)) from exc
            state.autopilot = pilot
        return pilot


def view(app, notice: str | None = None) -> dict:
    pilot = current(app)
    if pilot is not None:
        state, pending = pilot.state(), pilot.storage.pending_lines(pilot.scope)
    else:
        with Storage(app.state.trading_db) as st:
            state, pending = load_state(st, scope()), st.pending_lines(scope())
    return {
        "state": state.to_dict(),
        "modes": [{"key": k, "label": v} for k, v in MODE_LABELS.items()],
        "pending": pending,
        "notice": notice,
    }


def set_mode(app, mode: str) -> dict:
    pilot = current(app)
    if mode == "off" and pilot is None:     # nothing running: just record it
        with Storage(app.state.trading_db) as st:
            store_mode(st, scope(), mode, datetime.now(timezone.utc))
        return view(app)
    get(app).set_mode(mode)
    return view(app)


def approve(app, line_ids: list[int]) -> dict:
    asked = len(set(line_ids))
    done = get(app).approve(line_ids)
    notice = None
    if done < asked:
        notice = (f"{asked - done} of {asked} trades were not submitted: they had "
                  "expired (older than one poll) or were no longer pending.")
    return view(app, notice)


def reject(app, line_ids: list[int]) -> dict:
    get(app).reject(line_ids)
    return view(app)
