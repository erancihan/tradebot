"""History's yardstick: equal-weight buy and hold of the active symbol list.

"Is the bot beating just holding the list?" The answer is a plain index of
cached daily closes: at the last session close completed at or before
``since`` (the price the list could have been bought at when the first
snapshot was taken; the next close when no earlier one is cached) each
symbol gets ``start_equity / n``, and every later close is worth
``start_equity * mean_i(close_i,t / close_i,t0)``. The list is today's
active list, held from the start: a hindsight bias (a name added later
counts from day one). Pure and offline: the web layer reads the bar cache,
extended by the account's recorded bars (``benchmark_bars.py``), and never
fetches, so without daily bars there is no benchmark and the note says why.
The History card around it is ``benchmark_card.py``.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone

import pandas as pd

from ...data.cache import BarCache
from ...market.us import last_completed_close

#: Daily closes only: the benchmark is a session-by-session yardstick.
TIMEFRAME = "1day"
SOURCE = "cache"
#: Recorded bars (the autopilot's own, all but each symbol's newest) are in the window.
SOURCE_RECORDED = "cache+recorded"


def as_utc(ts: datetime) -> datetime:
    """Snapshot stamps are UTC; a naive one is read as UTC, never local time."""
    return ts if ts.tzinfo is not None else ts.replace(tzinfo=timezone.utc)


def completed_session(ts: datetime) -> date:
    """The session date of the newest close completed at or before ``ts``."""
    return last_completed_close(as_utc(ts)).date()


def _clean_closes(df: pd.DataFrame | None) -> pd.Series | None:
    """A frame's closes keyed by session date; bad prices are dropped (never sized)."""
    if df is None or df.empty or "close" not in df:
        return None
    closes = pd.to_numeric(df["close"], errors="coerce")
    closes = closes[closes.map(lambda v: math.isfinite(v) and v > 0)]
    if closes.empty:
        return None
    closes.index = [ts.date() for ts in closes.index]
    return closes[~closes.index.duplicated(keep="last")]


def _series(frames: dict[str, pd.DataFrame], until: datetime) -> dict[str, pd.Series]:
    """Each usable symbol's closes up to the last session completed by ``until``."""
    end = completed_session(until)
    series = {s: c for s, c in ((s, _clean_closes(f)) for s, f in frames.items())
              if c is not None}
    return {s: c[c.index <= end] for s, c in series.items()}


def window_closes(frames: dict[str, pd.DataFrame], since: datetime,
                  until: datetime) -> tuple[pd.DataFrame, list[str], list[str]]:
    """``(closes, used, dropped)`` over the sessions from ``since`` to ``until``.

    The start is the last session close completed at or before ``since``
    (the newest one any frame has), else the first session after it. A
    symbol is used when it has a close at that start; one that lacks it (or
    has no bars in the window) is dropped. The window ends at the last
    session every used symbol has a close for; inside it a one-name gap holds
    that name's last close (``ffill``).
    """
    series = _series(frames, until)
    t0 = _start(series, since)
    if t0 is None:
        return pd.DataFrame(), [], sorted(frames)
    series = {s: c[c.index >= t0] for s, c in series.items()}
    used = [s for s in frames if s in series and not series[s].empty
            and series[s].index[0] == t0]
    dropped = [s for s in frames if s not in used]
    if not used:
        return pd.DataFrame(), [], dropped
    end = min(series[s].index[-1] for s in used)
    closes = pd.DataFrame({s: series[s] for s in used}).sort_index()
    closes = closes[closes.index <= end].ffill()     # a one-name gap mid-window holds
    return closes, used, dropped


def _start(series: dict[str, pd.Series], since: datetime):
    """The session the list is bought at: the newest close whose close
    instant is at or before ``since`` (a snapshot taken mid-session buys at
    the previous close, so caching that day's close later cannot move the
    start), else the earliest one after it; None without closes."""
    day = completed_session(since)
    before = [c.index[c.index <= day][-1] for c in series.values()
              if not c[c.index <= day].empty]
    if before:
        return max(before)
    after = [c.index[c.index > day][0] for c in series.values()
             if not c[c.index > day].empty]
    return min(after) if after else None


def buy_and_hold(frames: dict[str, pd.DataFrame], start_equity: float,
                 since: datetime, until: datetime) -> pd.Series | None:
    """Equal-weight buy and hold of ``frames`` by session date, or None."""
    closes, used, _ = window_closes(frames, since, until)
    return _index(closes, start_equity) if used else None


def _index(closes: pd.DataFrame, start_equity: float) -> pd.Series:
    """``start_equity`` split equally at the first row, marked at every close."""
    return (start_equity * (closes / closes.iloc[0]).mean(axis=1)).rename("benchmark")


def load_frames(cache_dir: str, symbols: list[str]) -> dict[str, pd.DataFrame | None]:
    """Each symbol's cached daily bars (None when uncached); never fetches."""
    cache = BarCache(cache_dir)
    return {s: cache.load(s, TIMEFRAME) for s in symbols}


def _notes(series: dict[str, pd.Series], uncached: list[str], dropped: list[str],
           closes: pd.DataFrame, until: datetime) -> list[str]:
    """Why a name is missing, and which names end the window early."""
    parts = [f"no cached daily bars for {', '.join(uncached)}"] if uncached else []
    t0 = closes.index[0] if not closes.empty else None
    ended = [s for s in dropped if t0 is not None and s in series
             and not series[s].empty and series[s].index[-1] < t0]
    late = [s for s in dropped if s not in ended]
    parts += [f"bars for {s} end before the start (last {series[s].index[-1]})"
              for s in ended]
    if late:
        parts.append(f"no close at the start for {', '.join(late)}")
    latest = completed_session(until)
    if t0 is not None and closes.index[-1] < latest:
        short = [s for s in closes.columns if series[s].index[-1] < latest]
        parts += [f"{s} bars stop at {series[s].index[-1]}" for s in short]
    return parts


def compare(cache_dir: str, symbols: list[str], start_equity: float,
            since: datetime, until: datetime) -> dict:
    """``compare_frames`` over the cached daily bars alone."""
    return compare_frames(load_frames(cache_dir, symbols), symbols, start_equity,
                          since, until)


def compare_frames(frames: dict[str, pd.DataFrame | None], symbols: list[str],
                   start_equity: float, since: datetime, until: datetime,
                   recorded: dict[str, set] | None = None) -> dict:
    """The benchmark and its provenance: ``{series, symbols, since, until,
    source, note}``; ``series`` is None (and ``note`` says why) without bars.
    ``recorded`` names the session dates recorded bars added per symbol: the
    source says so when one of them is inside the window."""
    uncached = [s for s, f in frames.items() if f is None or f.empty]
    cached = {s: f for s, f in frames.items() if s not in uncached}
    closes, used, dropped = window_closes(cached, since, until)
    parts = _notes(_series(cached, until), uncached,
                   [s for s in dropped if s not in uncached], closes, until)
    if not symbols:
        parts = ["no symbols to hold"]
    elif not used and not parts:
        parts = [f"no cached daily closes in the window for {', '.join(symbols)}"]
    series = _index(closes, start_equity) if used else None
    window = set(closes.index) if used else set()
    source = SOURCE_RECORDED if any(window & (recorded or {}).get(s, set())
                                    for s in used) else SOURCE
    # The pull the note suggests starts a week earlier: the start close is before `since`.
    pull_start = (since - timedelta(days=7)).date().isoformat()
    return {"series": series, "symbols": used, "requested": list(symbols), "source": source,
            "pull_start": pull_start,
            "since": series.index[0].isoformat() if series is not None else None,
            "until": series.index[-1].isoformat() if series is not None else None,
            "note": "; ".join(parts) or None}


def unavailable(symbols: list[str], since: datetime, note: str) -> dict:
    """A ``compare`` result with no series, for a reason other than bars."""
    return {"series": None, "symbols": [], "requested": list(symbols), "source": SOURCE,
            "pull_start": (since - timedelta(days=7)).date().isoformat(),
            "since": None, "until": None, "note": note}
