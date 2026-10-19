"""Order and equity-snapshot records: the audit trail of what the bot did.

An order is logged the moment the broker accepts it; what the broker later
says became of it (``engine/fills.py``) lands in its fill columns. Every
reader that sums the log goes through :func:`effective_qty`.
"""

from __future__ import annotations

from ..broker.base import TERMINAL_STATUSES, LegFill, OrderStatus
from ..models import Order, utcnow

#: Terminal states in which the order did not (fully) fill.
UNFILLED_STATUSES = frozenset({"canceled", "expired", "rejected"})


def effective_qty(row: dict) -> float:
    """The unsigned shares an order row really moved.

    Any status with a known fill above zero (filled, partly filled, or a
    cancel or unknown state after a partial fill): the broker's
    ``filled_qty``. Cancelled, expired or rejected with nothing filled: 0.
    Filled with a reported 0: 0. Not asked yet, or still working with
    nothing filled: the ordered ``qty``, the log's old assumption."""
    status, filled = row.get("status"), row.get("filled_qty")
    if filled is not None and float(filled) > 0:
        return float(filled)
    if status in UNFILLED_STATUSES:
        return 0.0
    if status in ("filled", "partially_filled") and filled is not None:
        return float(filled)
    return float(row["qty"])


#: Orders of one mode with a known fill, oldest fill first: what History's
#: round trips are built from (rows above an id: a dry run's newest start, else
#: 0). Any status counts once shares moved (a cancel
#: after a partial fill too, as in :func:`effective_qty`); the web reader
#: (``web/repository/history.py``) runs the same query read-only. ``SELECT *``
#: so a log from before ``intent`` (the web never migrates) still reads.
FILLED_ORDERS_SQL = (
    "SELECT * FROM orders WHERE mode = ? AND id > ? AND filled_qty > 0"
    " AND fill_price IS NOT NULL ORDER BY COALESCE(filled_at, ts), ts, id")


def signed_effective_qty(row: dict) -> float:
    qty = effective_qty(row)
    return qty if row["side"] == "buy" else -qty


def apply_order(held: float, row: dict) -> float:
    """The position after one logged order. An ``exit`` reduces the holding
    at most to flat and never opens one (``portfolio_pnl.book``'s
    ``UnmatchedExit`` rule): selling a hand-bought name the log never saw
    reads flat, not short. Any other row (an entry, an old NULL row) adds."""
    delta = signed_effective_qty(row)
    if row.get("intent") != "exit":
        return held + delta
    if held * delta >= 0:                  # flat, or the same direction: nothing of ours
        return held
    return held + delta if abs(delta) < abs(held) else 0.0


def net_positions(rows) -> dict[str, float]:
    """Signed shares per symbol over order rows in log order, flat ones left out."""
    totals: dict[str, float] = {}
    for row in rows:
        totals[row["symbol"]] = apply_order(totals.get(row["symbol"], 0.0), row)
    return {s: q for s, q in sorted(totals.items()) if abs(q) > 1e-9}


class OrdersMixin:
    """Order/equity writes over ``self._conn``."""

    def record_order(self, order: Order, broker_order_id: str | None, mode: str,
                     price: float | None = None, intent: str | None = None) -> None:
        """Log one submitted order. ``price`` is the price its proposal line was
        sized at, kept so History can show the notional; None when unknown.
        ``intent`` is why it was sent: "entry" (opens or grows exposure) or
        "exit" (reduces or closes it); None when the caller cannot say."""
        self._conn.execute(
            "INSERT INTO orders (ts, symbol, side, qty, type, broker_order_id, mode, price,"
            " intent) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                order.created_at.isoformat(),
                order.symbol,
                order.side.value,
                order.qty,
                order.type.value,
                broker_order_id,
                mode,
                None if price is None else float(price),
                intent,
            ),
        )
        self._conn.commit()

    def open_orders(self, mode: str, since_ts: str) -> list[dict]:
        """Orders of ``mode`` a broker knows that may still change: never asked
        (from ``since_ts`` on), last seen in a non-terminal state (any age, so
        an old working order is still learned), or filled with a bracket leg
        still resting."""
        marks = ", ".join("?" for _ in TERMINAL_STATUSES)
        cur = self._conn.execute(
            "SELECT id, ts, symbol, side, qty, broker_order_id, status, filled_qty,"
            " fill_price, filled_at, legs_open FROM orders WHERE mode = ?"
            " AND broker_order_id IS NOT NULL AND ((status IS NULL AND ts >= ?)"
            f" OR status NOT IN ({marks}) OR legs_open = 1) ORDER BY ts, id",
            (mode, since_ts, *sorted(TERMINAL_STATUSES)))
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def filled_orders(self, mode: str) -> list[dict]:
        """Every order of ``mode`` with a known fill, in fill order."""
        cur = self._conn.execute(FILLED_ORDERS_SQL, (mode, 0))
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def set_order_fill(self, order_id: int, status: OrderStatus) -> None:
        """Store the broker's word on one logged order."""
        self._conn.execute(
            "UPDATE orders SET status = ?, filled_qty = ?, fill_price = ?, filled_at = ?,"
            " legs_open = ? WHERE id = ?",
            (status.status, float(status.filled_qty), status.fill_price,
             status.filled_at.isoformat() if status.filled_at else None,
             int(status.legs_open), int(order_id)))
        self._conn.commit()

    def record_leg_fill(self, symbol: str, leg: LegFill, mode: str) -> bool:
        """Log a filled bracket leg as an exit, once per broker id (a re-run
        of a reconcile or a bracket check inserts nothing); True if new."""
        if self._conn.execute("SELECT 1 FROM orders WHERE mode = ? AND broker_order_id = ?",
                              (mode, leg.broker_order_id)).fetchone():
            return False
        at = (leg.filled_at or utcnow()).isoformat()
        self._conn.execute(
            "INSERT INTO orders (ts, symbol, side, qty, type, broker_order_id, mode, price,"
            " status, filled_qty, fill_price, filled_at, intent)"
            " VALUES (?, ?, ?, ?, 'bracket', ?, ?, ?, 'filled', ?, ?, ?, 'exit')",
            (at, symbol, leg.side, float(leg.filled_qty), leg.broker_order_id, mode,
             float(leg.fill_price), float(leg.filled_qty), float(leg.fill_price), at))
        self._conn.commit()
        return True

    def record_equity(self, equity: float, cash: float, mode: str) -> None:
        self._conn.execute(
            "INSERT INTO equity_snapshots (ts, equity, cash, mode) VALUES (?, ?, ?, ?)",
            (utcnow().isoformat(), equity, cash, mode),
        )
        self._conn.commit()
