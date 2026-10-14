"""Universe selection: discover *candidate* symbols worth considering at all.

This sits upstream of everything: universe → selector (which of these to hold)
→ allocator (how much) → RiskManager (quantities). The universe changes rarely
(resolved at process start), while the selector re-ranks every bar.

The only live source is an Alpaca liquidity screen (owner decision): shortlist
today's most-active names, keep the ones Alpaca marks active + tradable, pull
recent daily bars in one batched request, and keep those above a minimum price
and rolling average dollar volume. Alpaca's free IEX feed reports only ~2% of
consolidated volume, so dollar-volume floors are conservative by construction —
set them accordingly.

Honesty note: a universe screened *today* and replayed over history is
survivorship-biased — fine for live-forward paper trading, not evidence for
historical claims. The engine records each resolved universe to SQLite so the
paper trail is point-in-time.

All Alpaca calls are lazy and injectable, so the screen itself tests offline.
"""

from __future__ import annotations
from typing import Any

from .alpaca import AlpacaLiquidityUniverse
from .screen import ActivesFetcher, BarsFetcher, LiquidityScreen, TradableFetcher

__all__ = ["ActivesFetcher", "AlpacaLiquidityUniverse", "BarsFetcher", "LiquidityScreen",
           "TradableFetcher", "UNIVERSES", "build_universe"]


UNIVERSES: dict[str, type[AlpacaLiquidityUniverse]] = {
    AlpacaLiquidityUniverse.name: AlpacaLiquidityUniverse,
}


def build_universe(name: str, params: dict[str, Any] | None = None):
    """Instantiate a universe source by name with keyword params from config."""
    try:
        cls = UNIVERSES[name]
    except KeyError:
        known = ", ".join(sorted(UNIVERSES))
        raise KeyError(f"Unknown universe source {name!r}. Known: {known}") from None
    return cls(**(params or {}))
