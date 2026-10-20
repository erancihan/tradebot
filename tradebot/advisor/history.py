"""How much history one pass hands the strategy, allocator and selector.

All of it the store or cache holds, bounded to the newest ``HISTORY_BARS``.
``supertrend``'s bands, ``rsi_reversion``'s held state and every EMA are
stateful over the whole frame, and a ranked selector's walk depends on where
its frame starts, so a verdict on a short fetch window can differ from the
Backtester's full-frame one. The engine pass (``engine/signals``) and the Today
refresh (``web/services/advisor_service``) both apply this one rule.
"""

from __future__ import annotations

#: About twenty years of daily bars: past this the head is dropped, so a
#: backtest over a longer window can differ on stateful strategies.
HISTORY_BARS = 5000


def bounded(frame):
    """The newest ``HISTORY_BARS`` rows of ``frame`` (all of a shorter one)."""
    return frame.iloc[-HISTORY_BARS:] if len(frame) > HISTORY_BARS else frame
