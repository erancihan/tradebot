"""Data-side steps of a rebalance pass: bars and selector history."""

from __future__ import annotations

import logging

log = logging.getLogger("tradebot.engine")


def fetch_frames(engine) -> dict[str, object]:
    """Recent bars per symbol, persisted for the dashboard and the selector.

    A symbol whose fetch fails drops out of this pass instead of killing it.
    Prices and signals are judged by ``advisor.propose``, not here.
    """
    frames: dict[str, object] = {}
    settings = engine.settings
    for sym in settings.symbols:
        try:
            bars = engine.data.history(
                sym, timeframe=settings.timeframe, lookback=engine._lookback_days()
            )
            if engine.storage is not None:
                # Persist the price history (idempotent) for the dashboard.
                engine.storage.record_bars(sym, settings.timeframe, bars, engine.mode)
            frames[sym] = bars
        except Exception:
            log.exception("Data fetch failed for %s; skipping it this pass", sym)
    return frames


def selector_frames(engine, fetched: dict[str, object]) -> dict[str, object]:
    """Full accumulated per-symbol history for the selector.

    The strategy is stateless over a bounded window, so the fetched frames
    are fine for it. A `RankedSelector` is not: its hysteresis walk carries
    `held` from an empty set, so a verdict depends on where the frame
    *starts*. Feeding it the rolling fetch window made live selection depend
    on process start time and diverge from the backtest that validated it.

    Every fetched bar is already persisted by `fetch_frames`, so the store
    holds a superset of the window. Without a store (or before any history has
    accumulated) we fall back to the fetched frames — same behaviour as
    before, and the only honest option when there is nothing else to read.
    """
    if engine.storage is None:
        return fetched
    out: dict[str, object] = {}
    for sym, window in fetched.items():
        try:
            stored = engine.storage.load_bars(sym, engine.settings.timeframe, engine.mode)
        except Exception:
            log.exception("Could not read stored bars for %s; using the fetch window", sym)
            stored = None
        out[sym] = stored if stored is not None and len(stored) >= len(window) else window
    return out
