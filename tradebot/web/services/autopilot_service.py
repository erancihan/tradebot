"""The Autopilot page's data and commands.

The account scope follows the server's credentials: with Alpaca keys the
autopilot trades the *paper* account ("paper"); without them it runs a
dry-run over the cached bars ("dry_run"). The web never reaches a live
account, so there is no mode here that could.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ...autopilot import MODE_LABELS, load_state, store_mode
from ...config import AlpacaCredentials
from ...storage import Storage


def scope() -> str:
    return "paper" if AlpacaCredentials.from_env() is not None else "dry_run"


def view(app) -> dict:
    with Storage(app.state.trading_db) as st:
        state = load_state(st, scope())
        pending = st.pending_lines(scope())
    return _shape(state, pending)


def set_mode(app, mode: str) -> dict:
    with Storage(app.state.trading_db) as st:
        store_mode(st, scope(), mode, datetime.now(timezone.utc))
    return view(app)


def _shape(state, pending: list[dict]) -> dict:
    return {
        "state": state.to_dict(),
        "modes": [{"key": k, "label": v} for k, v in MODE_LABELS.items()],
        "pending": pending,
    }
