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

import logging
import threading
from datetime import datetime, timezone

from ...autopilot import MODE_LABELS, Autopilot, load_state, store_mode
from ...config import AlpacaCredentials
from ...storage import Storage
from . import autopilot_build

log = logging.getLogger("tradebot.web.autopilot")

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
            # ValueError: a stored config a component rejects (e.g. a
            # hand-edited negative brief). Reported, never a 500 or a server
            # that fails to start.
            except (RuntimeError, ValueError) as exc:
                raise AutopilotUnavailable(str(exc)) from exc
            state.autopilot = pilot
        return pilot


def view(app, notice: str | None = None) -> dict:
    pilot = current(app)
    if pilot is not None:
        state, pending = pilot.state(), pilot.storage.pending_lines(pilot.account)
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
    pilot = get(app)
    pilot.set_mode(mode)
    if mode != "off":
        pilot.start()     # once: a running loop just reads the new mode next wake
    # "off" needs nothing more: set_mode set the stop event the sleep waits on.
    return view(app)


def resume(app) -> None:
    """At server start: pick the loop back up if the stored mode is on, so a
    restart does not silently stop an autopilot the user left running."""
    with Storage(app.state.trading_db) as st:
        mode = load_state(st, scope()).mode
    if mode == "off":
        return
    try:
        get(app).start()
    except AutopilotUnavailable as exc:
        log.warning("Autopilot left %s but cannot resume: %s", mode, exc)


def shutdown(app) -> None:
    pilot = current(app)
    if pilot is not None:
        pilot.stop()


def reset(app) -> bool:
    """After a settings save: stop the loop and drop the runner, so the next
    command builds one from the new settings. Returns whether a loop was running.

    The stored mode is left alone, so the page still shows what the user chose
    and a restart resumes it; it simply is not running on stale settings.
    """
    with _BUILD_LOCK:
        pilot = current(app)
        app.state.autopilot = None
    if pilot is None:
        return False
    was_running = pilot.running
    pilot.stop()
    return was_running


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
