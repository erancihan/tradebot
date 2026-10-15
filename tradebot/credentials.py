"""Broker credentials, read from the environment (or a local ``.env``).

Kept apart from ``Settings`` so the YAML configuration never carries a secret
and so the trading core can ask "are there credentials?" without loading a
config file.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _maybe_load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv()


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
