"""Data-side steps of a rebalance pass: bars and the stored history."""

from __future__ import annotations

import logging

from ..advisor.history import HISTORY_BARS, bounded

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


def history_frames(engine, fetched: dict[str, object]) -> dict[str, object]:
    """Full accumulated per-symbol history for the strategy, allocator and selector.

    A strategy is not stateless over a bounded window: ``supertrend``'s bands,
    ``rsi_reversion``'s held state and every EMA carry state from the first
    bar, and a `RankedSelector` walk carries `held` from an empty set. On the
    rolling fetch window a verdict depended on when the process started and
    diverged from the full-frame backtest that validated it.

    Every fetched bar is already persisted by `fetch_frames`, so the store
    holds a superset of the window, read back bounded by
    ``advisor.history.HISTORY_BARS``. Without a store (or before any history
    has accumulated) we fall back to the fetched frames: the only honest
    option when there is nothing else to read.
    """
    if engine.storage is None:
        return {sym: bounded(window) for sym, window in fetched.items()}
    out: dict[str, object] = {}
    for sym, window in fetched.items():
        try:
            stored = engine.storage.load_bars(sym, engine.settings.timeframe, engine.mode,
                                              limit=HISTORY_BARS)
        except Exception:
            log.exception("Could not read stored bars for %s; using the fetch window", sym)
            stored = None
        use = stored if stored is not None and len(stored) >= len(window) else window
        out[sym] = bounded(use)
    return out
