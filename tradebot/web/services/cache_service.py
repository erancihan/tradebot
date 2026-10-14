"""Read-only inventory of the local bar cache (``data/cache``).

The dashboard stays credential-free on purpose: this service only ever reads
what ``tradebot data pull`` (or a scenario's first run) already wrote to disk.
It never fetches — a range the cache cannot prove is answered with the exact
pull command to run, not with a network call.
"""

from __future__ import annotations

from pathlib import Path


def inventory(cache_dir: str | Path) -> list[dict]:
    """Every cached (symbol, timeframe): bar span, count, and pulled windows."""
    from ...data.cache import _MAX_TS, _MIN_TS, BarCache

    root = Path(cache_dir)
    if not root.exists():
        return []
    cache = BarCache(root)
    entries: list[dict] = []
    for csv in sorted(root.glob("*/*.csv")):
        timeframe, symbol = csv.parent.name, csv.stem
        df = cache.load(symbol, timeframe)
        if df is None or df.empty:
            continue
        entries.append({
            "symbol": symbol,
            "timeframe": timeframe,
            "bars": int(len(df)),
            "first": df.index.min().isoformat(),
            "last": df.index.max().isoformat(),
            "coverage": [
                {"start": None if lo == _MIN_TS else lo.isoformat(),
                 "end": None if hi == _MAX_TS else hi.isoformat()}
                for lo, hi in cache.coverage(symbol, timeframe)
            ],
        })
    return entries
