"""Which settings a process runs with: one rule for `tradebot` and `tradebot-web`.

An explicit path wins, then ``TRADEBOT_CONFIG``; either must exist. The
implicit ``config.yaml`` in the working directory is used only when present,
so both entry points run without one.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import Settings

#: What runs when no config file exists: a broad market pair, so a fresh
#: install has something meaningful to show.
DEFAULT_SYMBOLS = ["SPY", "QQQ"]

#: The file picked up from the working directory when no path is given.
IMPLICIT_CONFIG = "config.yaml"

#: The environment variable naming the config file when no path is given.
CONFIG_ENV = "TRADEBOT_CONFIG"


def config_path(path: str | None) -> str | None:
    """The file to load: ``path``, else ``$TRADEBOT_CONFIG``, else ``./config.yaml``
    when present, else None (defaults). The first two are explicit: a missing
    file raises when loaded rather than falling back silently."""
    if path is not None:
        return path
    # The `.env` in the working directory may set it, as it may the keys.
    from .credentials import _maybe_load_dotenv

    _maybe_load_dotenv()
    env = os.environ.get(CONFIG_ENV)
    if env:
        return env
    return IMPLICIT_CONFIG if Path(IMPLICIT_CONFIG).exists() else None


def resolve_settings(path: str | None) -> tuple[Settings, str | None]:
    """``(Settings, source)``: the settings and the file they came from (None = defaults)."""
    from .config import Settings  # noqa: F811 - config imports this module

    path = config_path(path)
    if path is None:
        return Settings(symbols=list(DEFAULT_SYMBOLS)), None
    return Settings.from_yaml(path), str(path)
