"""Bars for several symbols at once (the What-if page), with provenance.

Same two sources and the same rule as :mod:`.frames`: ``real`` reads the local
cache only, and a miss is answered with the exact pull command for every
missing symbol at once, so one terminal command fixes the whole plan.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .frames import MAX_PERIODS, MIN_REAL_BARS, _pull_hint

SYNTHETIC_START = "2021-01-04"
SYNTHETIC_BARS = 750                  # about three years of business days


def _synthetic_many(symbols: list[str], start, end, seed: int) -> tuple[dict, dict]:
    from ....data.synthetic import synthetic_ohlcv

    begin = pd.Timestamp(start or SYNTHETIC_START)
    periods = (len(pd.bdate_range(begin, end)) if end else SYNTHETIC_BARS)
    periods = max(MIN_REAL_BARS, min(periods, MAX_PERIODS))
    # One seed per symbol, so the names do not move in lockstep.
    frames = {sym: synthetic_ohlcv(periods=periods, start=str(begin.date()), freq="B",
                                   seed=seed + i)
              for i, sym in enumerate(symbols)}
    first = next(iter(frames.values()))
    return frames, {
        "source": "synthetic", "symbol": ",".join(symbols), "seed": seed,
        "bars": int(len(first)),
        "start": first.index.min().isoformat(), "end": first.index.max().isoformat(),
        "note": "invented prices — dates are labels, not history or a forecast",
    }


def _cached_one(cache, sym: str, timeframe: str, start, end) -> pd.DataFrame | None:
    """A fully bounded range must be vouched for by the coverage manifest; an
    open-ended one means "as far as the cache goes", so it reads what is there.
    """
    if start and end:
        try:
            return cache.get(sym, timeframe, start=start, end=end, fetcher=None)
        except RuntimeError:
            return None
    df = cache.load(sym, timeframe)
    if df is None:
        return None
    keep = np.ones(len(df), dtype=bool)
    if start:
        keep &= df.index >= pd.Timestamp(start, tz=df.index.tz)
    if end:   # half-open on the right, like BarCache._slice
        keep &= df.index < pd.Timestamp(end, tz=df.index.tz)
    return df[keep]


def _cached_many(symbols: list[str], start, end, timeframe: str,
                 cache_dir: str) -> tuple[dict, dict]:
    from ....data.cache import BarCache

    cache = BarCache(cache_dir)
    frames, missing = {}, []
    for sym in symbols:
        df = _cached_one(cache, sym, timeframe, start, end)
        if df is None or df.empty:
            missing.append(sym)
        else:
            frames[sym] = df
    if missing:
        raise RuntimeError(
            f"no cached bars for {', '.join(missing)} ({timeframe}) covering that "
            f"range. Pull once with: {_pull_hint(' '.join(missing), timeframe, start, end)}"
        )
    common = None
    for df in frames.values():
        common = df.index if common is None else common.intersection(df.index)
    if len(common) < MIN_REAL_BARS:
        raise RuntimeError(f"only {len(common)} shared cached bars in that range — "
                           f"fewer than {MIN_REAL_BARS} is noise. Widen the range.")
    if len(common) > MAX_PERIODS:
        raise RuntimeError(f"{len(common)} bars exceeds the {MAX_PERIODS}-bar job limit — "
                           "narrow the range.")
    return frames, {
        "source": "real", "symbol": ",".join(symbols), "timeframe": timeframe,
        "bars": int(len(common)),
        "start": common.min().isoformat(), "end": common.max().isoformat(),
        "note": "cached Alpaca bars — raw/unadjusted prices, simulated fills and costs",
    }


def resolve_many(params: dict) -> tuple[dict[str, pd.DataFrame], dict]:
    """Every plan symbol's bars plus one provenance record for the whole set."""
    symbols = [str(s).upper() for s in params["symbols"]]
    start, end = params.get("start") or None, params.get("end") or None
    if str(params.get("source") or "real") == "synthetic":
        return _synthetic_many(symbols, start, end, int(params.get("seed", 42)))
    return _cached_many(symbols, start, end, str(params.get("timeframe") or "1day"),
                        params.get("cache_dir") or "data/cache")
