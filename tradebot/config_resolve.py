"""Which settings a process runs with: one rule for `tradebot` and `tradebot-web`.

An explicit path must exist; the implicit ``config.yaml`` in the working
directory is used only when present, so both entry points run without one.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import Settings

#: What runs when no config file exists: a broad market pair, so a fresh
#: install has something meaningful to show.
DEFAULT_SYMBOLS = ["SPY", "QQQ"]

#: The file picked up from the working directory when no path is given.
IMPLICIT_CONFIG = "config.yaml"


def resolve_settings(path: str | None) -> tuple[Settings, str | None]:
    """``(Settings, source)``: the settings and the file they came from (None = defaults)."""
    from .config import Settings  # noqa: F811 - config imports this module

    if path is None and Path(IMPLICIT_CONFIG).exists():
        path = IMPLICIT_CONFIG
    if path is None:
        return Settings(symbols=list(DEFAULT_SYMBOLS)), None
    return Settings.from_yaml(path), str(path)
