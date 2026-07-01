"""Local OHLCV cache: pull once, replay forever.

``BarCache`` persists fetched bars to local CSV files keyed by symbol + timeframe
and serves subsequent requests from disk. A request that the cache can't fully
cover triggers a fetch (via an injected ``Fetcher``), the new bars are merged in,
and the union is persisted — so a given (symbol, timeframe, range) is downloaded
at most once and everything afterwards is reproducible and offline.

The ``Fetcher`` is injected so the cache has zero hard dependency on Alpaca (and
is trivially testable). :func:`build_default_fetcher` wires the real Alpaca
adapter when credentials are present.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import pandas as pd

from ..models import BAR_COLUMNS


class Fetcher(Protocol):
    def __call__(self, symbol: str, timeframe: str, start, end) -> pd.DataFrame: ...


def _ts(value) -> pd.Timestamp | None:
    if value is None:
        return None
    return pd.Timestamp(value, tz="UTC") if pd.Timestamp(value).tzinfo is None else pd.Timestamp(value)


class BarCache:
    def __init__(self, root: str | Path = "data/cache") -> None:
        self.root = Path(root)

    def path(self, symbol: str, timeframe: str) -> Path:
        return self.root / timeframe / f"{symbol.upper()}.csv"

    def load(self, symbol: str, timeframe: str) -> pd.DataFrame | None:
        p = self.path(symbol, timeframe)
        if not p.exists():
            return None
        df = pd.read_csv(p)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.set_index("timestamp").sort_index()
        return df[[c for c in BAR_COLUMNS if c in df.columns]]

    def store(self, symbol: str, timeframe: str, df: pd.DataFrame) -> None:
        p = self.path(symbol, timeframe)
        p.parent.mkdir(parents=True, exist_ok=True)
        out = df.copy()
        out.index.name = "timestamp"
        out.to_csv(p)

    def get(
        self,
        symbol: str,
        timeframe: str = "1day",
        start=None,
        end=None,
        fetcher: Fetcher | None = None,
    ) -> pd.DataFrame:
        """Return bars for ``[start, end]``, fetching+caching only on a miss."""
        start, end = _ts(start), _ts(end)
        cached = self.load(symbol, timeframe)

        if not self._covers(cached, start, end):
            if fetcher is None:
                raise RuntimeError(
                    f"No cached data for {symbol} ({timeframe}) covering the requested "
                    "range and no fetcher available. Provide credentials or pre-populate "
                    "the cache (e.g. `tradebot data pull`)."
                )
            fetched = fetcher(symbol, timeframe, start, end)
            cached = self._merge(cached, fetched)
            self.store(symbol, timeframe, cached)

        return self._slice(cached, start, end)

    # --- helpers -------------------------------------------------------------
    @staticmethod
    def _covers(df: pd.DataFrame | None, start, end) -> bool:
        if df is None or df.empty:
            return False
        if start is not None and df.index.min() > start:
            return False
        if end is not None and df.index.max() < end:
            return False
        return True

    @staticmethod
    def _merge(existing: pd.DataFrame | None, fresh: pd.DataFrame) -> pd.DataFrame:
        combined = fresh if existing is None else pd.concat([existing, fresh])
        combined = combined[~combined.index.duplicated(keep="last")].sort_index()
        return combined[[c for c in BAR_COLUMNS if c in combined.columns]]

    @staticmethod
    def _slice(df: pd.DataFrame, start, end) -> pd.DataFrame:
        return df.loc[start:end]


class AlpacaFetcher:
    """Adapts :class:`tradebot.data.alpaca_data.AlpacaData` to the Fetcher protocol."""

    def __init__(self, data) -> None:
        self._data = data

    def __call__(self, symbol: str, timeframe: str, start, end) -> pd.DataFrame:
        return self._data.bars(symbol, timeframe=timeframe, start=start, end=end)


def build_default_fetcher() -> Fetcher | None:
    """An Alpaca-backed fetcher if credentials are in the environment, else None."""
    from ..config import AlpacaCredentials

    creds = AlpacaCredentials.from_env()
    if creds is None:
        return None
    from .alpaca_data import AlpacaData

    return AlpacaFetcher(AlpacaData(creds.api_key, creds.api_secret, feed=creds.feed))
