"""History's yardstick: equal-weight buy and hold of the active symbol list.

"Is the bot beating just holding the list?" The answer is a plain index of
cached daily closes: at the last session close on or before ``since`` (the
price the list could have been bought at that morning; the next close when
no earlier one is cached) each symbol gets ``start_equity / n``, and every
later close is worth ``start_equity * mean_i(close_i,t / close_i,t0)``. Pure and offline: the
web layer reads the bar cache and never fetches, so without cached daily
bars there is no benchmark and the note says why.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

import pandas as pd

from ...data.cache import BarCache
from . import symbols_service

#: Daily closes only: the benchmark is a session-by-session yardstick.
TIMEFRAME = "1day"
SOURCE = "cache"


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


def window_closes(frames: dict[str, pd.DataFrame], since: datetime,
                  until: datetime) -> tuple[pd.DataFrame, list[str], list[str]]:
    """``(closes, used, dropped)`` over the sessions from ``since`` to ``until``.

    The start is the last session close on or before ``since``'s date (the
    newest one any frame has), else the first session after it. A symbol is
    used when it has a close at that start; one that lacks it (or has no bars
    in the window) is dropped. The window ends at the last session every used
    symbol has, so no point is a carried-forward guess.
    """
    series = {s: c for s, c in ((s, _clean_closes(f)) for s, f in frames.items())
              if c is not None}
    series = {s: c[c.index <= until.date()] for s, c in series.items()}
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
    """The session the list is bought at: the newest close on or before
    ``since``'s date, else the earliest one after it; None without closes."""
    day = since.date()
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


def compare(cache_dir: str, symbols: list[str], start_equity: float,
            since: datetime, until: datetime) -> dict:
    """The benchmark and its provenance: ``{series, symbols, since, until,
    source, note}``; ``series`` is None (and ``note`` says why) without bars."""
    frames = load_frames(cache_dir, symbols)
    uncached = [s for s, f in frames.items() if f is None or f.empty]
    closes, used, dropped = window_closes(
        {s: f for s, f in frames.items() if s not in uncached}, since, until)
    late = [s for s in dropped if s not in uncached]
    parts = []
    if uncached:
        parts.append(f"no cached daily bars for {', '.join(uncached)}")
    if late:
        parts.append(f"no close at the start for {', '.join(late)}")
    if not symbols:
        parts = ["no symbols to hold"]
    elif not used and not parts:
        parts = [f"no cached daily closes in the window for {', '.join(symbols)}"]
    series = _index(closes, start_equity) if used else None
    # The pull the note suggests starts a week earlier: the start close is before `since`.
    pull_start = (since - timedelta(days=7)).date().isoformat()
    return {"series": series, "symbols": used, "requested": list(symbols), "source": SOURCE,
            "pull_start": pull_start,
            "since": series.index[0].isoformat() if series is not None else None,
            "until": series.index[-1].isoformat() if series is not None else None,
            "note": "; ".join(parts) or None}


# --- History glue: the snapshots' window, the active list -------------------

#: The card names at most this many symbols, then "+N more".
SHOWN_SYMBOLS = 6


def for_snapshots(repo, settings, cache_dir: str, rows: list[dict]) -> dict | None:
    """The benchmark over equity snapshots ``rows`` (oldest first), starting
    from the first one's equity, for the list the autopilot trades."""
    if not rows:
        return None
    symbols = symbols_service.active_symbols(settings, repo)
    return compare(cache_dir, symbols, float(rows[0]["equity"]),
                   datetime.fromisoformat(rows[0]["ts"]),
                   datetime.fromisoformat(rows[-1]["ts"]))


def card(bench: dict | None, start: float, pct: float | None) -> dict:
    """The performance card's third cell: alpha against holding the list."""
    if bench is None or bench["series"] is None:
        return {"present": False, "note": bench["note"] if bench else None,
                "missing": bench["requested"] if bench else [],
                "pull_start": bench["pull_start"] if bench else None}
    now = float(bench["series"].iloc[-1])
    bench_pct = now / start - 1.0 if start else None
    shown = bench["symbols"][:SHOWN_SYMBOLS]
    return {"present": True, "now": now, "pct": bench_pct,
            "alpha": pct - bench_pct if pct is not None and bench_pct is not None else None,
            "symbols": bench["symbols"], "shown": shown,
            "more": len(bench["symbols"]) - len(shown),
            "since": bench["since"], "until": bench["until"],
            "source": bench["source"], "note": bench["note"]}
