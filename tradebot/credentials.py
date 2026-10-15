"""Broker credentials, read from the environment (or a local ``.env``).

Kept apart from ``Settings`` so the YAML configuration never carries a secret
and so the trading core can ask "are there credentials?" without loading a
config file.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _maybe_load_dotenv() -> None:
    """Fill unset variables from the ``.env`` in the working directory, only.

    A bare ``load_dotenv()`` searches upward from the *calling module's*
    directory: under systemd a checkout's development ``.env`` silently filled
    variables the EnvironmentFile left unset, and a non-editable install under
    launchd found nothing. The working directory is what a service file sets.
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    path = Path.cwd() / ".env"
    if path.is_file():
        load_dotenv(dotenv_path=path, override=False)


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
