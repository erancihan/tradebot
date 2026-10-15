"""History's Trades card: round trips and realised P&L for one account.

Built from the bot's own filled orders (``portfolio_pnl``, average cost), so
hand trades in the same account are not included and a partial fill counts
the shares that filled. Open positions carry no P&L: the log has no prices.
"""

from __future__ import annotations

from ...models import Trade
from ...portfolio_pnl import OpenTrade, book, fills_from_orders, summary

#: Where the trades come from, said beside them.
SOURCE = "order log fills"


def _closed(trade: Trade) -> dict:
    return {"symbol": trade.symbol, "side": trade.side, "qty": trade.qty,
            "entry_price": trade.entry_price, "exit_price": trade.exit_price,
            "pnl": trade.pnl, "pnl_pct": trade.pnl_pct,
            "entry_ts": trade.entry_ts.isoformat() if trade.entry_ts else None,
            "exit_ts": trade.timestamp.isoformat()}


def _open(lot: OpenTrade) -> dict:
    return {"symbol": lot.symbol, "side": lot.side, "qty": lot.qty,
            "avg_price": lot.avg_price, "entry_ts": lot.entry_ts.isoformat(),
            "realised": lot.realised}


def view(repo, mode: str) -> dict:
    """Closed trips newest first, what is still open, their summary, and
    provenance (the account, the source, how many orders were read)."""
    rows = repo.filled_orders(mode)
    closed, still = book(fills_from_orders(rows))
    return {"mode": mode, "summary": summary(closed),
            "trades": [_closed(t) for t in reversed(closed)],
            "open": [_open(o) for o in still],
            "provenance": {"mode": mode, "source": SOURCE, "orders": len(rows)}}
