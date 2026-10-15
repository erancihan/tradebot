"""Broker credentials, read from the environment (or a local ``.env``).

Kept apart from ``Settings`` so the YAML configuration never carries a secret
and so the trading core can ask "are there credentials?" without loading a
config file.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


#: The only keys a ``.env`` may set. The file sits in whatever directory the
#: process starts in, so it is treated as untrusted: a stray ``PATH``,
#: ``PYTHONPATH`` or ``LD_PRELOAD`` in it must never reach the environment.
DOTENV_KEYS = ("ALPACA_API_KEY", "ALPACA_API_SECRET", "ALPACA_DATA_FEED",
               "TRADEBOT_WEB_TOKEN", "TRADEBOT_ALLOWED_HOSTS", "TRADEBOT_LIVE_CONFIRM",
               "TRADEBOT_DB", "TRADEBOT_ARENA_DB", "TRADEBOT_SEASON_DB", "TRADEBOT_CONFIG")


def _maybe_load_dotenv() -> None:
    """Fill unset ``DOTENV_KEYS`` from the ``.env`` in the working directory, only.

    A bare ``load_dotenv()`` searches upward from the *calling module's*
    directory: under systemd a checkout's development ``.env`` silently filled
    variables the EnvironmentFile left unset, and a non-editable install under
    launchd found nothing. The working directory is what a service file sets.
    Variables already set win; any other key in the file is ignored.
    """
    try:
        from dotenv import dotenv_values
    except ImportError:
        return
    path = Path.cwd() / ".env"
    if not path.is_file():
        return
    values = dotenv_values(path)
    for key in DOTENV_KEYS:
        value = values.get(key)
        if value is not None and key not in os.environ:
            os.environ[key] = value


@dataclass
class AlpacaCredentials:
    api_key: str
    api_secret: str
    feed: str = "iex"

    @classmethod
    def from_env(cls) -> "AlpacaCredentials | None":
        _maybe_load_dotenv()
        key = os.getenv("ALPACA_API_KEY")
        secret = os.getenv("ALPACA_API_SECRET")
        if not key or not secret:
            return None
        return cls(api_key=key, api_secret=secret, feed=os.getenv("ALPACA_DATA_FEED", "iex"))
