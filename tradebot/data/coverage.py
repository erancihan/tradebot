"""Coverage manifests for the bar cache: which windows a provider was asked for.

A ``*.coverage.json`` beside each cached CSV lists the windows requested from a
provider. When a manifest exists it is authoritative, gaps included — disjoint
pulls stay separate entries so a request spanning a hole re-fetches instead of
trusting data never downloaded.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

# Stand-ins for an unbounded coverage edge, kept inside pandas' representable
# range so they compare like any other timestamp. Serialised back out as null.
_MIN_TS = pd.Timestamp("1678-01-01", tz="UTC")
_MAX_TS = pd.Timestamp("2261-01-01", tz="UTC")


def _ts(value) -> pd.Timestamp | None:
    if value is None:
        return None
    return pd.Timestamp(value, tz="UTC") if pd.Timestamp(value).tzinfo is None else pd.Timestamp(value)


#: A symbol or timeframe as a cache file name: no separator, so never a path.
_NAME = re.compile(r"^[A-Za-z0-9.\-]{1,32}$")


def check_cache_name(symbol: str, timeframe: str) -> None:
    """Raise ``ValueError`` unless both are plain names: whoever calls the
    cache, a symbol or timeframe never reaches a file outside it."""
    for name in (str(symbol), str(timeframe)):
        if not _NAME.match(name) or set(name) <= {"."}:
            raise ValueError(f"not a cache name: {symbol!r} ({timeframe!r}); symbols "
                             "and timeframes never leave the cache directory")


#: Timeframe names that mean one bar per session.
DAILY = frozenset({"1day", "1d", "day"})


def complete_through(timeframe: str, end, now) -> pd.Timestamp | None:
    """``end``, clamped for daily bars to the last completed session's close.

    During market hours a provider returns today's still-forming daily bar;
    cached as final, it would never be refetched. Intraday timeframes and an
    ``end`` already in the past pass through unchanged.
    """
    if str(timeframe).lower() not in DAILY:
        return end
    from ..market.us import last_completed_close

    done = pd.Timestamp(last_completed_close(now)).tz_convert("UTC")
    return done if end is None or end > done else end


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


def read_manifest(path: Path) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Windows recorded in a manifest file, merged and sorted."""
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError):
        return []          # an unreadable manifest just means "prove it by fetching"
    return _merge_windows([
        (_ts(w.get("start")) or _MIN_TS, _ts(w.get("end")) or _MAX_TS) for w in raw
    ])


def write_manifest(path: Path, windows: list[tuple[pd.Timestamp, pd.Timestamp]],
                   start, end) -> None:
    """Persist ``windows`` plus the newly pulled ``[start, end]``."""
    windows = list(windows)
    windows.append((_ts(start) or _MIN_TS, _ts(end) or _MAX_TS))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([
        {"start": None if lo == _MIN_TS else lo.isoformat(),
         "end": None if hi == _MAX_TS else hi.isoformat()}
        for lo, hi in _merge_windows(windows)
    ], indent=1))
