"""The Today page's holdings card: what the account owns, at what price.

With Alpaca credentials the positions and equity come from the **paper**
broker (never live, as everywhere in the web layer). Without them they come
from the SQLite order log, the same signed-sum the Today refresh uses, so the
card and the proposal's "held" column always agree. Prices are the last
cached close: the web layer reads the bar cache and never fetches here.
"""

from __future__ import annotations

import logging
import math

from ...data.cache import BarCache
from ..repository import TradingRepository
from . import advisor_service

log = logging.getLogger("tradebot.web.holdings")


def view(settings, *, trading_db: str, cache_dir: str) -> dict:
    """``{source, equity, rows, skipped, note}``; rows are largest value first."""
    positions, avg_cost, equity, source, note = _book(settings, trading_db)
    cache, rows, skipped = BarCache(cache_dir), [], []
    for symbol, qty in sorted(positions.items()):
        price, as_of = _last_close(cache, symbol, settings.timeframe)
        if price is None and symbol in avg_cost:
            # A real broker position is never hidden for want of a cached
            # bar; its cost basis stands in, and the row says so.
            price, as_of = avg_cost[symbol], "cost basis"
        if price is None:
            skipped.append(symbol)
            continue
        value = qty * price
        rows.append({"symbol": symbol, "qty": qty, "price": price, "value": value,
                     "weight": value / equity if equity > 0 else None, "as_of": as_of})
    rows.sort(key=lambda r: -abs(r["value"]))
    return {"source": source, "equity": equity, "rows": rows,
            "skipped": skipped, "note": note}


def _book(settings, trading_db: str):
    """(positions, avg_cost, equity, source, note) from the broker, else the log."""
    creds = advisor_service._credentials()
    if creds is not None:
        try:
            broker = advisor_service._paper_broker(creds)
            held = {s: p for s, p in broker.positions().items() if not p.is_flat}
            return ({s: float(p.qty) for s, p in held.items()},
                    {s: float(p.avg_price) for s, p in held.items()},
                    float(broker.account().equity), "alpaca", None)
        except Exception as exc:  # noqa: BLE001 - a broker hiccup never breaks the page
            log.warning("Alpaca holdings unavailable, using the order log: %s", exc)
            note = "Alpaca did not answer; showing the order log instead."
    else:
        note = None
    repo = TradingRepository(trading_db)
    latest = repo.latest_equity_for(settings.mode)
    equity = float(latest["equity"]) if latest else float(settings.initial_cash)
    return repo.positions_from_orders(settings.mode), {}, equity, "log", note


def _last_close(cache: BarCache, symbol: str, timeframe: str):
    """(close, date) of the newest cached bar, or (None, None) when uncached."""
    df = cache.load(symbol, timeframe)
    if df is None or df.empty:
        return None, None
    close = float(df["close"].iloc[-1])
    if not math.isfinite(close) or close <= 0:     # bad prices are flat, everywhere
        return None, None
    return close, df.index[-1].date().isoformat()
