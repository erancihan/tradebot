"""Market-data sources. The Alpaca adapter lazily imports the SDK so the rest of
the package (and the test suite) works without it installed."""

from __future__ import annotations

from .replay import ReplayData
from .synthetic import load_csv, synthetic_ohlcv

__all__ = ["synthetic_ohlcv", "load_csv", "ReplayData", "get_alpaca_data"]


def get_alpaca_data(*args, **kwargs):
    """Lazy accessor for the Alpaca data client (avoids importing the SDK eagerly)."""
    from .alpaca_data import AlpacaData

    return AlpacaData(*args, **kwargs)
