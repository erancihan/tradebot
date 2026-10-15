"""Held names off the list, read and priced for ``advisor.propose``.

The list is the mandate: a position the list does not name is closed. This
module only gathers the inputs (the broker's positions minus the list, and a
last close for each); the advisor decides the line.
"""

from __future__ import annotations

import logging
import math

from ..advisor.unlisted import off_list

log = logging.getLogger("tradebot.engine")

#: Calendar days of bars fetched to price an off-list holding: enough to
#: span a long weekend, and nothing a signal would need.
PRICE_LOOKBACK = 10


def read_unlisted(engine) -> dict[str, tuple[float, float | None]]:
    """``symbol -> (signed qty, last close or None)`` for held names off the list.

    A failed positions read yields nothing: the list's own pass goes on.
    """
    try:
        held = {s: float(p.qty) for s, p in engine.broker.positions().items()}
    except Exception:  # noqa: BLE001 - an off-list read never kills the pass
        log.exception("Positions read failed; off-list holdings wait for the next pass")
        return {}
    extra = off_list(held, engine.settings.symbols)
    if not extra:
        return {}
    prices = _prices(engine, list(extra))
    return {s: (q, prices.get(s)) for s, q in extra.items()}


def _prices(engine, symbols: list[str]) -> dict[str, float]:
    """The newest valid close per symbol: one batched fetch when the data
    source has one, else one short fetch each. A miss is simply absent."""
    tf = engine.settings.timeframe
    many = getattr(engine.data, "history_many", None)
    try:
        if many is not None:
            frames = many(symbols, timeframe=tf, lookback=PRICE_LOOKBACK)
        else:
            frames = {s: _one(engine, s, tf) for s in symbols}
    except Exception:  # noqa: BLE001 - no price means a skipped line, not a crash
        log.exception("Price fetch failed for off-list holdings %s", symbols)
        return {}
    out: dict[str, float] = {}
    for sym, bars in frames.items():
        if bars is None or len(bars) == 0:
            continue
        close = float(bars["close"].iloc[-1])
        if math.isfinite(close) and close > 0:      # bad prices are flat
            out[sym] = close
    return out


def _one(engine, symbol: str, timeframe: str):
    try:
        return engine.data.history(symbol, timeframe=timeframe, lookback=PRICE_LOOKBACK)
    except Exception:  # noqa: BLE001 - this symbol goes unpriced, the rest do not
        log.warning("No bars for off-list holding %s; its line is skipped", symbol)
        return None
