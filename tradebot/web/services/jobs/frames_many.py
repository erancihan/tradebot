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
#: Invented bars before a synthetic plan's start: the warmup the plan's stack
#: decides its first bar from (the longest default selector needs 253).
SYNTHETIC_WARMUP = 300


def _synthetic_many(symbols: list[str], start, end, seed: int) -> tuple[dict, dict]:
    from ....data.synthetic import synthetic_ohlcv

    begin = pd.Timestamp(start or SYNTHETIC_START)
    periods = (len(pd.bdate_range(begin, end)) if end else SYNTHETIC_BARS)
    if periods < MIN_REAL_BARS:            # never padded past ``end``: refused
        raise RuntimeError(f"only {periods} bars in that range — fewer than "
                           f"{MIN_REAL_BARS} is noise. Widen the range.")
    periods = min(periods, MAX_PERIODS)
    first = pd.bdate_range(end=begin, periods=SYNTHETIC_WARMUP + 1)[0]
    # One seed per symbol, so the names do not move in lockstep.
    frames = {sym: synthetic_ohlcv(periods=SYNTHETIC_WARMUP + periods, start=str(first.date()),
                                   freq="B", seed=seed + i)
              for i, sym in enumerate(symbols)}
    # Provenance from the bars the plan runs on, after the warmup.
    own = next(iter(frames.values())).index[SYNTHETIC_WARMUP:]
    return frames, {
        "source": "synthetic", "symbol": ",".join(symbols), "seed": seed,
        "bars": int(len(own)),
        "start": own.min().isoformat(), "end": own.max().isoformat(),
        "note": "invented prices — dates are labels, not history or a forecast",
    }


def _cached_one(cache, sym: str, timeframe: str, start, end) -> pd.DataFrame | None:
    """A fully bounded range must be vouched for by the coverage manifest; an
    open-ended one means "as far as the cache goes", so it reads what is there.
    The cached bars before ``start`` ride along as the plan's warmup (the
    what-if trims them to what its stack needs); they are not the plan's range.
    """
    df = cache.load(sym, timeframe)
    if start and end:
        try:
            cache.get(sym, timeframe, start=start, end=end, fetcher=None)
        except RuntimeError:
            return None
    if df is None:
        return None
    if end:   # half-open on the right, like BarCache._slice
        df = df[df.index < pd.Timestamp(end, tz=df.index.tz)]
    return df


def _own(df: pd.DataFrame, start) -> pd.DataFrame:
    """The bars from ``start`` on: the plan's range, without its warmup."""
    return df[df.index >= pd.Timestamp(start, tz=df.index.tz)] if start else df


def _cached_many(symbols: list[str], start, end, timeframe: str,
                 cache_dir: str) -> tuple[dict, dict]:
    from ....data.cache import BarCache

    cache = BarCache(cache_dir)
    frames, missing = {}, []
    for sym in symbols:
        df = _cached_one(cache, sym, timeframe, start, end)
        if df is None or _own(df, start).empty:
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
        own = _own(df, start).index
        common = own if common is None else common.intersection(own)
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
