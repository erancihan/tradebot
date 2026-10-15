"""Season drive loops: the thin replay loop and the market-hours daemon."""

from __future__ import annotations

import time

from .model import Season


def run_season(season: Season, feed, max_ticks: int | None = None,
               poll_seconds: float = 0.0, pace_s: float = 0.0,
               stop_on_empty: bool = True, on_step=None,
               supervise: bool = False, on_error=None) -> int:
    """Drive a season from a feed. Returns the number of ticks applied.

    ``stop_on_empty=True`` (replay) stops when the feed is exhausted;
    ``stop_on_empty=False`` (live) waits ``poll_seconds`` for the next bar.
    With ``supervise=True`` a failing tick is caught (``on_error(exc)``) and the
    loop continues instead of crashing the run.
    """
    ticks = 0
    while max_ticks is None or ticks < max_ticks:
        bar = feed.next()
        if bar is None:
            if stop_on_empty:
                break
            if poll_seconds:
                time.sleep(poll_seconds)
                continue
            break
        try:
            snapshot = season.step(bar)
        except Exception as exc:  # noqa: BLE001 - daemon survives a bad tick
            if not supervise:
                raise
            if on_error is not None:
                on_error(exc)
            snapshot = None
        ticks += 1
        if snapshot is not None and on_step is not None:
            on_step(snapshot)
        if pace_s:
            time.sleep(pace_s)
    return ticks


def run_season_daemon(season: Season, feed, poll_seconds: float = 60.0,
                      ignore_market_hours: bool = False, max_ticks: int | None = None,
                      on_step=None, on_error=None, clock=None, sleep=None,
                      stop_on_empty: bool = False, calendar=None) -> int:
    """Daemon loop: gate on market hours, drop still-forming bars, step under
    supervision. Returns the number of ticks applied.

    ``calendar`` (a `MarketCalendar`, default US) drives only the gate: the
    partial-bar drop stays on US hours because the bars are Alpaca's.

    ``clock`` (-> tz-aware now) and ``sleep`` are injected so the *whole* loop is
    testable/runnable offline — pass a simulated clock + no-op sleep + a replay
    feed (that's what ``season run --simulate`` does). ``stop_on_empty`` ends the
    run when a (replay) feed is exhausted instead of polling forever.
    """
    from datetime import datetime, timezone

    from ...market import get_calendar

    calendar = calendar or get_calendar("us_equities")
    if clock is None:
        clock = lambda: datetime.now(timezone.utc)  # noqa: E731
    if sleep is None:
        sleep = time.sleep

    ticks = 0
    # `max_ticks` counts *applied* ticks, so on its own it cannot terminate a run
    # whose feed never yields — a closed market or a dry feed spins without ever
    # incrementing it. Bound the loop itself too, generously enough that the tick
    # budget is what normally ends a healthy run.
    spins, max_spins = 0, None if max_ticks is None else max_ticks * 100 + 1000
    while max_ticks is None or ticks < max_ticks:
        if max_spins is not None and spins >= max_spins:
            break
        spins += 1
        now = clock()
        if not ignore_market_hours and not calendar.is_open(now):
            sleep(poll_seconds)
            continue
        bar = feed.next()
        if bar is None:
            if stop_on_empty:
                break
            sleep(poll_seconds)
            continue
        bar = _settled(bar, season.config.timeframe, now)
        if not bar:
            sleep(poll_seconds)
            continue
        try:
            snapshot = season.step(bar)
            if snapshot is not None and on_step is not None:
                on_step(snapshot)
        except Exception as exc:  # noqa: BLE001
            if on_error is not None:
                on_error(exc)
        ticks += 1
        sleep(poll_seconds)
    return ticks


def _settled(bar: dict, timeframe: str, now) -> dict:
    """The bar with each symbol's still-forming last row dropped; a symbol
    left with nothing drops out."""
    from ..market import drop_incomplete_bars

    bar = {s: drop_incomplete_bars(df, timeframe, now) for s, df in bar.items()}
    return {s: df for s, df in bar.items() if df is not None and len(df) > 0}
