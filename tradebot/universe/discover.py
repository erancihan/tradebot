"""Discover: rank names the owner does not watch or hold, by 6-1 momentum.

A suggestion of names, never a trade (ADR 0002). The pool comes from the
caller (Alpaca's most-active screen, or every daily frame in the local cache),
passes the same ``LiquidityScreen`` the universe uses, and is scored with
``MomentumSelector.scores`` itself, one symbol at a time so a short or ragged
history never shrinks another symbol's window. Frames are cut at ``as_of``, so
no bar after that date is ever read; the provenance says which date that was.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Iterable

import pandas as pd

from ..selection.ranked import MomentumSelector
from .screen import LiquidityScreen

#: 6-month momentum skipping the last month, in trading days.
LOOKBACK = 126
SKIP = 21
TOP_N = 10
#: A frame whose newest bar trails the pool's newest by more sessions than
#: this is a name the cache stopped updating: its momentum is old news.
MAX_STALE_SESSIONS = 5

FramesFor = Callable[[list[str]], "dict[str, pd.DataFrame]"]


@dataclass(frozen=True)
class DiscoverRow:
    symbol: str
    score: float          # momentum as a fraction: 0.34 = up 34%
    price: float          # last close on or before as_of
    adv: float            # average dollar volume over the screen's window
    reason: str


@dataclass
class DiscoverResult:
    rows: list[DiscoverRow]
    provenance: dict = field(default_factory=dict)

    def row_dicts(self) -> list[dict]:
        return [asdict(r) for r in self.rows]


def cached_daily_symbols(cache_dir: str | Path) -> list[str]:
    """Every symbol with a cached daily frame (``<cache>/1day/<SYM>.csv``)."""
    root = Path(cache_dir) / "1day"
    return sorted(p.stem for p in root.glob("*.csv")) if root.exists() else []


def short_money(value: float) -> str:
    """$42M, $1.2B, $850K: one glance, not an accounting figure."""
    for unit, size in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(value) >= size:
            scaled = value / size
            return f"${scaled:.1f}{unit}" if scaled < 10 else f"${scaled:.0f}{unit}"
    return f"${value:.0f}"


def reason_for(score: float, adv: float) -> str:
    direction = "Up" if score >= 0 else "Down"
    return (f"{direction} {abs(score) * 100:.0f}% over 6 months to last month; "
            f"{short_money(adv)} a day traded.")


def _cut(df: pd.DataFrame, as_of: date | None) -> pd.DataFrame:
    """Bars on or before ``as_of`` only (daily stamps sit at 04:00/05:00 UTC)."""
    if as_of is None or df.empty:
        return df
    bound = pd.Timestamp(as_of + timedelta(days=1), tz=df.index.tz)
    return df[df.index < bound]


def drop_stale(frames: dict[str, pd.DataFrame],
               limit: int = MAX_STALE_SESSIONS) -> tuple[dict[str, pd.DataFrame], int]:
    """``frames`` minus those ending over ``limit`` sessions before the newest.

    Sessions are the pool's own: the distinct stamps any frame has a bar on,
    so a frame is stale when more than ``limit`` of them come after its end.
    """
    ends = {s: f.index.max() for s, f in frames.items() if not f.empty}
    if not ends:
        return frames, 0
    days = pd.DatetimeIndex(sorted({d for f in frames.values() for d in f.index}))
    kept = {s: f for s, f in frames.items()
            if s not in ends or int((days > ends[s]).sum()) <= limit}
    return kept, len(frames) - len(kept)


def sessions_behind(newest: date, now) -> int:
    """US sessions completed after ``newest`` up to ``now``: how far a pool's
    newest bar trails what a fresh pull would have."""
    from ..market.us import is_trading_day, last_completed_close

    done = last_completed_close(now).date()
    days = pd.date_range(newest + timedelta(days=1), done, freq="D")
    return sum(1 for d in days if is_trading_day(d.date()))


def momentum_score(df: pd.DataFrame, lookback: int = LOOKBACK, skip: int = SKIP) -> float:
    """The newest ``MomentumSelector`` score for one frame (NaN when too short)."""
    selector = MomentumSelector(lookback=lookback, skip=skip, top_k=1)
    if len(df) < selector.required_history:
        return math.nan
    return float(selector.scores({"_": df}).iloc[-1, 0])


def discover(frames_for: FramesFor, pool: Iterable[str], *, lookback: int = LOOKBACK,
             skip: int = SKIP, top_n: int = TOP_N, exclude: Iterable[str] = (),
             screen: LiquidityScreen | None = None, as_of: date | None = None,
             source: str = "cache") -> DiscoverResult:
    """The ``top_n`` best-scoring screened names in ``pool`` minus ``exclude``."""
    skipped = {str(s).upper() for s in exclude}
    candidates = list(dict.fromkeys(s for s in pool if s.upper() not in skipped))
    screen = screen or LiquidityScreen()
    frames = {s: _cut(df, as_of) for s, df in (frames_for(candidates) if candidates
                                               else {}).items() if df is not None}
    frames, stale = drop_stale(frames)
    rows: list[DiscoverRow] = []
    for metrics in screen.details(frames):
        sym = str(metrics["symbol"])
        score = momentum_score(frames[sym], lookback, skip)
        if not math.isfinite(score):
            continue                       # warmup-short or a bad price: unrankable
        adv = float(metrics["adv"])
        rows.append(DiscoverRow(sym, score, float(metrics["price"]), adv,
                                reason_for(score, adv)))
    rows.sort(key=lambda r: (-r.score, r.symbol))
    scored = {r.symbol for r in rows}
    used = [f for s, f in frames.items() if s in scored and not f.empty]
    return DiscoverResult(rows[:top_n], _provenance(
        source, as_of, used, pool=len(candidates), screened=len(frames),
        ranked=len(rows), stale=stale, excluded=sorted(skipped), lookback=lookback,
        skip=skip))


def _provenance(source: str, as_of: date | None, used: list[pd.DataFrame],
                **counts) -> dict:
    """What the ranking ran on: source, window, bar count, and the as-of cut."""
    start = min((f.index.min() for f in used), default=None)
    end = max((f.index.max() for f in used), default=None)
    return {
        "source": source, "timeframe": "1day",
        "as_of": as_of.isoformat() if as_of else (end.date().isoformat() if end else None),
        "start": start.isoformat() if start is not None else None,
        "end": end.isoformat() if end is not None else None,
        "bars": int(sum(len(f) for f in used)),
        **counts,
        "note": ("momentum = close 21 bars ago / close 126 bars ago - 1, raw daily "
                 "closes; names to look at, not trades"),
    }
