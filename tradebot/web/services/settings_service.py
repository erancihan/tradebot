"""The Settings page's data: the editable part of ``config.yaml``.

The page edits the same document a hand-written config file holds
(``config_io.settings_to_dict``), so whatever the phone saves is exactly what
``tradebot run --config`` would read. Secrets are never part of it: the page
only learns whether the server environment has Alpaca keys.
"""

from __future__ import annotations

from pathlib import Path

from ...config import AlpacaCredentials
from ...config_io import editable, settings_to_dict
from ...data.alpaca_data import _TIMEFRAME_ALIASES
from ...market.registry import CALENDARS

#: Where a save goes when the server started without a config file.
DEFAULT_CONFIG = "config.yaml"


def target_path(state) -> Path:
    return Path(state.settings_path or DEFAULT_CONFIG)


def credentials_present() -> bool:
    return AlpacaCredentials.from_env() is not None


def view(app, notice: str | None = None) -> dict:
    """``GET /api/settings``: the editable document plus what frames it."""
    state = app.state
    path = target_path(state)
    return {
        "settings": editable(settings_to_dict(state.settings)),
        "mode": state.settings.mode,
        "credentials_present": credentials_present(),
        "config_path": str(path),
        "config_exists": path.exists(),
        "choices": {"markets": sorted(CALENDARS), "timeframes": list(_TIMEFRAME_ALIASES)},
        "notice": notice,
    }
