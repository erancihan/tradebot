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

import json
from pathlib import Path
from typing import Protocol

import pandas as pd

from ..models import BAR_COLUMNS

# Stand-ins for an unbounded coverage edge, kept inside pandas' representable
# range so they compare like any other timestamp. Serialised back out as null.
_MIN_TS = pd.Timestamp("1678-01-01", tz="UTC")
_MAX_TS = pd.Timestamp("2261-01-01", tz="UTC")


class Fetcher(Protocol):
    def __call__(self, symbol: str, timeframe: str, start, end) -> pd.DataFrame: ...


def _ts(value) -> pd.Timestamp | None:
    if value is None:
        return None
    return pd.Timestamp(value, tz="UTC") if pd.Timestamp(value).tzinfo is None else pd.Timestamp(value)


def _merge_windows(
    windows: list[tuple[pd.Timestamp, pd.Timestamp]],
) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Merge overlapping/touching windows, leaving disjoint ones separate.

    Two pulls with a gap between them stay two entries on purpose: a later
    request spanning the gap must re-fetch rather than trust a hole it never
    downloaded.
    """
    merged: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    for start, end in sorted(windows):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _spans(windows: list[tuple[pd.Timestamp, pd.Timestamp]], start, end) -> bool:
    """True if one recorded window contains ``[start, end]`` outright.

    The manifest records what we *asked* the provider for, which is the honest
    coverage signal: whatever bars came back inside that window are, by
    definition, all the bars that exist there. Observed timestamps can't say
    that — a requested boundary landing on a weekend, a holiday, or before the
    session open simply has no bar to compare against.
    """
    lo = _ts(start) or _MIN_TS
    hi = _ts(end) or _MAX_TS
    return any(a <= lo and hi <= b for a, b in windows)


class BarCache:
    def __init__(self, root: str | Path = "data/cache") -> None:
        self.root = Path(root)

    def path(self, symbol: str, timeframe: str) -> Path:
        return self.root / timeframe / f"{symbol.upper()}.csv"

    def coverage_path(self, symbol: str, timeframe: str) -> Path:
        return self.root / timeframe / f"{symbol.upper()}.coverage.json"

    def coverage(self, symbol: str, timeframe: str) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
        """Provider windows already pulled for this symbol, merged and sorted."""
        p = self.coverage_path(symbol, timeframe)
        if not p.exists():
            return []
        try:
            raw = json.loads(p.read_text())
        except (OSError, ValueError):
            return []          # an unreadable manifest just means "prove it by fetching"
        return _merge_windows([
            (_ts(w.get("start")) or _MIN_TS, _ts(w.get("end")) or _MAX_TS) for w in raw
        ])

    def record_coverage(self, symbol: str, timeframe: str, start, end) -> None:
        """Note that ``[start, end]`` was fetched from a provider for this symbol."""
        windows = self.coverage(symbol, timeframe)
        windows.append((_ts(start) or _MIN_TS, _ts(end) or _MAX_TS))
        p = self.coverage_path(symbol, timeframe)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps([
            {"start": None if lo == _MIN_TS else lo.isoformat(),
             "end": None if hi == _MAX_TS else hi.isoformat()}
            for lo, hi in _merge_windows(windows)
        ], indent=1))

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
                covered = cached is not None and _spans(pulled, start, end)
        else:
            covered = self._covers(cached, start, end)

        if not covered:
            if fetcher is None:
                raise RuntimeError(
                    f"No cached data for {symbol} ({timeframe}) covering the requested "
                    "range and no fetcher available. Provide credentials or pre-populate "
                    "the cache (e.g. `tradebot data pull`)."
                )
            fetched = fetcher(symbol, timeframe, start, end)
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
                hi = end if end is not None else _ts(fetched.index.max())
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
