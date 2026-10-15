"""Held names off the list, priced from the bar cache, for the Today refresh.

The list is the mandate (``advisor/unlisted.py``): the refresh hands the
advisor every holding the list does not name, so Today shows the same
sell-to-flat line the autopilot would submit. Prices are the last cached
close; an uncached name gets no price and its line is skipped, never guessed.
"""

from __future__ import annotations

import math

from ...advisor.unlisted import off_list
from ...data.cache import BarCache


def unlisted(positions: dict[str, float], symbols, *, cache_dir: str,
             timeframe: str) -> dict[str, tuple[float, float | None]]:
    """``symbol -> (signed qty, last cached close or None)`` off the list."""
    cache = BarCache(cache_dir)
    return {s: (q, last_close(cache, s, timeframe)[0])
            for s, q in off_list(positions, symbols).items()}


def last_close(cache: BarCache, symbol: str, timeframe: str):
    """(close, date) of the newest cached bar, or (None, None) when uncached."""
    try:
        df = cache.load(symbol, timeframe)
    except Exception:  # noqa: BLE001 - an unreadable cache file is an unpriced name
        return None, None
    if df is None or df.empty:
        return None, None
    close = float(df["close"].iloc[-1])
    if not math.isfinite(close) or close <= 0:     # bad prices are flat, everywhere
        return None, None
    return close, df.index[-1].date().isoformat()
