"""The benchmark's closes: the bar cache, extended by the account's recorded bars.

The cache fills only on a Today refresh or ``tradebot data pull``, while every
autopilot pass records the daily bars it fetched into the trading db
(``storage/bars.record_bars``). Without them the yardstick falls a session or
more behind the bot. Each symbol's newest recorded bar may still be forming
(the record is an upsert for that reason), so it is never used; a recorded bar
followed by a later one was delivered as a completed session. Where both
sources hold a session date the cached close wins (the cache never holds a
forming bar). Only a broker account's bars count: a dry run replays whatever
frame it was given (a ``--replay`` of synthetic bars records them under
``dry_run`` with real symbol names), so its benchmark stays cache-only.
Read through the repository; never fetches.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from . import benchmark

#: The bars table keeps one row per session per symbol and account, so 2000
#: rows is about eight years of daily bars: far more than any snapshot window.
RECORDED_LIMIT = 2000
#: Accounts whose recorded bars are real closes from the broker's feed.
RECORDED_ACCOUNTS = ("paper", "live")


def recorded(repo, symbol: str, mode: str) -> pd.DataFrame | None:
    """``symbol``'s recorded daily bars for account ``mode`` except the newest
    (it may be forming), indexed by UTC timestamp; None when nothing is left
    or ``mode`` is not a broker account."""
    if mode not in RECORDED_ACCOUNTS:
        return None
    rows = repo.bars(symbol, limit=RECORDED_LIMIT, timeframe=benchmark.TIMEFRAME,
                     mode=mode)[:-1]
    if not rows:
        return None
    df = pd.DataFrame(rows)
    df.index = pd.to_datetime(df.pop("ts"), utc=True)
    return df


def _day(ts) -> date:
    return ts.date()


def merge(cached: pd.DataFrame | None,
          stored: pd.DataFrame | None) -> tuple[pd.DataFrame | None, set[date]]:
    """``(frame, added)``: the cached bars plus every recorded bar on a session
    date the cache lacks, and those added dates."""
    if stored is None or stored.empty:
        return cached, set()
    have = set() if cached is None or cached.empty else {_day(t) for t in cached.index}
    extra = stored[[_day(t) not in have for t in stored.index]]
    if extra.empty:
        return cached, set()
    parts = [f for f in (cached, extra[["close"]]) if f is not None and not f.empty]
    frame = pd.concat(parts).sort_index() if len(parts) > 1 else parts[0]
    return frame, {_day(t) for t in extra.index}


def load(repo, cache_dir: str, symbols: list[str],
         mode: str) -> tuple[dict[str, pd.DataFrame | None], dict[str, set[date]]]:
    """Each symbol's merged daily bars and the session dates recorded bars added."""
    frames, added = {}, {}
    for symbol, cached in benchmark.load_frames(cache_dir, symbols).items():
        frames[symbol], added[symbol] = merge(cached, recorded(repo, symbol, mode))
    return frames, added


__all__ = ["RECORDED_ACCOUNTS", "RECORDED_LIMIT", "load", "merge", "recorded"]
