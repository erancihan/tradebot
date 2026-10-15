"""Local OHLCV cache: pull once, replay forever.

``BarCache`` persists fetched bars to local CSV files keyed by symbol + timeframe
and serves subsequent requests from disk. A request that the cache can't fully
cover triggers a fetch (via an injected ``Fetcher``), the new bars are merged in,
and the union is persisted — so a given (symbol, timeframe, range) is downloaded
at most once and everything afterwards is reproducible and offline.

Coverage is tracked two ways. Alongside each CSV a small ``*.coverage.json``
manifest records the windows actually pulled from a provider; a request inside a
pulled window is served from disk even when no bar sits on its boundaries. That
matters for real calendars: asking for ``2021-12-01`` yields a first daily bar
stamped at the ``05:00`` UTC open, and an end date on a weekend or holiday has no
bar at all — judging coverage by observed timestamps alone would re-fetch
forever. Caches with no manifest (hand-seeded, or written before this existed)
fall back to the stricter observed-bar check.

The ``Fetcher`` is injected so the cache has zero hard dependency on Alpaca (and
is trivially testable). :func:`build_default_fetcher` wires the real Alpaca
adapter when credentials are present.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Protocol

import pandas as pd

from ..models import BAR_COLUMNS
from .coverage import (  # noqa: F401  (_MIN_TS/_MAX_TS/_merge_windows re-exported)
    _MAX_TS,
    _MIN_TS,
    _merge_windows,
    _spans,
    _ts,
    complete_through,
    read_manifest,
    write_manifest,
)


class Fetcher(Protocol):
    def __call__(self, symbol: str, timeframe: str, start, end) -> pd.DataFrame: ...


class BarCache:
    def __init__(self, root: str | Path = "data/cache",
                 clock: Callable[[], datetime] | None = None) -> None:
        self.root = Path(root)
        # Injected so tests can stand in the middle of a session.
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def path(self, symbol: str, timeframe: str) -> Path:
        return self.root / timeframe / f"{symbol.upper()}.csv"

    def coverage_path(self, symbol: str, timeframe: str) -> Path:
        return self.root / timeframe / f"{symbol.upper()}.coverage.json"

    def coverage(self, symbol: str, timeframe: str) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
        """Provider windows already pulled for this symbol, merged and sorted."""
        return read_manifest(self.coverage_path(symbol, timeframe))

    def record_coverage(self, symbol: str, timeframe: str, start, end) -> None:
        """Note that ``[start, end]`` was fetched from a provider for this symbol."""
        write_manifest(self.coverage_path(symbol, timeframe),
                       self.coverage(symbol, timeframe), start, end)

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
        """Return bars for ``[start, end]``, fetching+caching only on a miss.

        A daily request reaching past the last completed session is fetched,
        judged and recorded only up to that session's close (``upto``), so a
        forming bar never lands in the cache.
        """
        start, end = _ts(start), _ts(end)
        upto = complete_through(timeframe, end, self._clock())
        cached = self.load(symbol, timeframe)
        if start is not None and upto is not None and upto < start:
            # Nothing in the window has closed yet: there is nothing to fetch.
            return self._slice(cached, start, end) if cached is not None else _empty()
        pulled = self.coverage(symbol, timeframe)
        if pulled:
            # A manifest means these windows came from a provider, so they are
            # authoritative — including about the gaps between them.
            if start is None and end is None:
                # An unbounded read asks for "whatever is cached", not for proof
                # that every date in history is present — which nothing bounded
                # could ever satisfy.
                covered = cached is not None and not cached.empty
            else:
                covered = cached is not None and _spans(pulled, start, upto)
        else:
            # No manifest: an open end still means "whatever is cached".
            covered = self._covers(cached, start, None if end is None else upto)

        if not covered:
            if fetcher is None:
                raise RuntimeError(
                    f"No cached data for {symbol} ({timeframe}) covering the requested "
                    "range and no fetcher available. Provide credentials or pre-populate "
                    "the cache (e.g. `tradebot data pull`)."
                )
            fetched = fetcher(symbol, timeframe, start, upto)
            if fetched is not None and upto is not None and upto is not end:
                fetched = fetched[fetched.index <= upto]       # the forming bar
            cached = self._merge(cached, fetched)
            self.store(symbol, timeframe, cached)
            # Never claim coverage wider than what the provider actually handed
            # back. An empty response proves nothing about the window, and an
            # unbounded request used to record an unbounded claim — after which
            # `_spans` answered True for *every* later range and a window that
            # was never downloaded came back as an empty frame instead of being
            # re-fetched.
            if fetched is not None and len(fetched):
                lo = start if start is not None else _ts(fetched.index.min())
                bounded = start is not None or end is not None
                hi = upto if bounded and upto is not None else _ts(fetched.index.max())
                self.record_coverage(symbol, timeframe, lo, hi)

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


def _empty() -> pd.DataFrame:
    return pd.DataFrame(columns=list(BAR_COLUMNS),
                        index=pd.DatetimeIndex([], tz="UTC", name="timestamp"))


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
