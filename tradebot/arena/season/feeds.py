"""Season feeds — each tick yields the new bar(s) per symbol.

Replay drives it offline/in tests, Alpaca polls live (lazy SDK), and the
stream adapter buffers a push source into the same pull-shaped ``next()``.
"""

from __future__ import annotations

import math
import threading

import pandas as pd

from ...market.us import _TF_DURATION
from ...models import utcnow

#: Minutes in a regular US session, to turn intraday bars into sessions.
_SESSION_MINUTES = 390


def catchup_days(bars: int, timeframe: str) -> int:
    """Calendar days that hold ``bars`` bars of ``timeframe``.

    ``AlpacaData.history`` reads ``lookback`` as calendar days; passing the bar
    count healed only about two thirds of it (weekends, holidays). Same margin
    as the web's frame fetch: x1.5 for weekends plus 10 days of holidays.
    """
    step = _TF_DURATION.get(timeframe)
    sessions = bars if step is None else math.ceil(
        bars * step.total_seconds() / 60 / _SESSION_MINUTES)
    return math.ceil(sessions * 1.5) + 10


class ReplaySeasonFeed:
    """Replays pre-built frames one bar at a time (offline / tests / demo)."""

    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self._frames = frames
        self._cursor = 0
        self._max = min(len(f) for f in frames.values()) if frames else 0

    def next(self) -> dict[str, pd.DataFrame] | None:
        if self._cursor >= self._max:
            return None
        bar = {s: f.iloc[[self._cursor]] for s, f in self._frames.items()}
        self._cursor += 1
        return bar


class AlpacaSeasonFeed:
    """Live one-bar-per-poll feed (lazy Alpaca; not exercised by the test suite)."""

    def __init__(self, symbols, timeframe: str, api_key: str, api_secret: str,
                 feed: str = "iex", data=None, clock=utcnow, catchup: int = 30) -> None:
        self._symbols = list(symbols)
        self._timeframe = timeframe
        #: How far back each poll looks. This is the outage the feed can heal
        #: from on its own: a machine that slept through a long weekend, a
        #: reboot, a crashed daemon. Beyond it, re-seed (`arena season seed`).
        self._catchup = max(int(catchup), 2)
        if data is None:
            from ...data.alpaca_data import AlpacaData

            data = AlpacaData(api_key, api_secret, feed=feed)
        self._data = data
        self._clock = clock
        self._last_ts: dict[str, pd.Timestamp] = {}

    def next(self) -> dict[str, pd.DataFrame] | None:
        """Every *complete* bar per symbol that has not been delivered yet.

        Two things this must get right, both learned the hard way:

        1. **Completeness is filtered HERE, before the dedup** — not by the
           caller. The daemon also drops still-forming bars, and when that was
           the only filter a bar first polled while it was still forming got
           marked as seen, then thrown away, and was never offered again once it
           settled. A live daily season accumulated zero bars while reporting
           healthy ticks.
        2. **Every new bar, not just the newest one.** Returning only
           ``df.iloc[[-1]]`` meant any gap between polls punched a permanent
           hole in the season's history: a machine asleep over a weekend, a
           reboot, a crashed daemon. Bars are the source of truth and standings
           are recomputed from them, so a hole silently changes every later
           ranking while the season still reports healthy — the same failure
           shape as the bug in (1). Measured on a 9-bar gap: 7 bars lost.

        Because ``_last_ts`` lives in memory, a fresh process re-offers its whole
        catch-up window; the season's ``(season_id, symbol, ts)`` primary key
        makes that idempotent, so a restart heals rather than skips. An outage
        longer than ``catchup`` needs ``arena season seed``.
        """
        from ..market import drop_incomplete_bars

        now = self._clock()
        bar: dict[str, pd.DataFrame] = {}
        for symbol in self._symbols:
            df = self._data.history(symbol, timeframe=self._timeframe,
                                    lookback=catchup_days(self._catchup, self._timeframe))
            if df is None or df.empty:
                continue
            df = drop_incomplete_bars(df, self._timeframe, now)
            if df is None or len(df) == 0:
                continue
            df = df.iloc[-self._catchup:]   # the window is in bars, not days
            seen = self._last_ts.get(symbol)
            fresh = df if seen is None else df[df.index > seen]
            if not len(fresh):
                continue  # nothing settled since the last poll
            self._last_ts[symbol] = pd.Timestamp(fresh.index[-1])
            bar[symbol] = fresh
        return bar or None


class StreamSeasonFeed:
    """Adapts a push-based bar stream (``data/stream.py``) to the feed protocol.

    A season pulls one bar per symbol per tick; a stream pushes whenever the
    provider sends. This buffers the difference: pushed bars queue per symbol
    and ``next()`` drains one from each. Nothing is dropped and nothing is
    reordered, so a season fed by a stream accumulates exactly what a polling
    feed would have — the season's PK dedup still backstops duplicates.

    ``start(background=False)`` runs the stream inline, which is what makes a
    ``FakeStream`` deterministic in tests: it pushes every bar and returns
    before a single ``next()`` is called. Live callers want the daemon thread.
    """

    def __init__(self, stream, symbols) -> None:
        self._stream = stream
        self._symbols = list(symbols)
        self._pending: dict[str, list[pd.DataFrame]] = {s: [] for s in self._symbols}
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def _on_bar(self, symbol: str, frame: pd.DataFrame) -> None:
        with self._lock:
            self._pending.setdefault(symbol, []).append(frame)

    def start(self, background: bool = True) -> None:
        if background:
            self._thread = threading.Thread(
                target=self._stream.run, args=(self._symbols, self._on_bar),
                name="season-stream", daemon=True,
            )
            self._thread.start()
        else:
            self._stream.run(self._symbols, self._on_bar)

    def stop(self) -> None:
        self._stream.stop()

    def next(self) -> dict[str, pd.DataFrame] | None:
        with self._lock:
            bar = {s: q.pop(0) for s, q in self._pending.items() if q}
        return bar or None
