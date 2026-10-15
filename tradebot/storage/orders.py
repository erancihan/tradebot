"""Order and equity-snapshot records: the audit trail of what the bot did.

An order is logged the moment the broker accepts it; what the broker later
says became of it (``engine/fills.py``) lands in its fill columns. Every
reader that sums the log goes through :func:`effective_qty`.
"""

from __future__ import annotations

from ..broker.base import TERMINAL_STATUSES, OrderStatus
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
#: round trips are built from. Any status counts once shares moved (a cancel
#: after a partial fill too, as in :func:`effective_qty`); the web reader
#: (``web/repository/history.py``) runs the same query read-only. ``SELECT *``
#: so a log from before ``intent`` (the web never migrates) still reads.
FILLED_ORDERS_SQL = (
    "SELECT * FROM orders WHERE mode = ? AND filled_qty > 0 AND fill_price IS NOT NULL"
    " ORDER BY COALESCE(filled_at, ts), ts, id")


def signed_effective_qty(row: dict) -> float:
    qty = effective_qty(row)
    return qty if row["side"] == "buy" else -qty


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
        """Orders of ``mode`` from ``since_ts`` on that a broker knows and that
        may still change: never asked, or last seen in a non-terminal state."""
        marks = ", ".join("?" for _ in TERMINAL_STATUSES)
        cur = self._conn.execute(
            "SELECT id, ts, symbol, side, qty, broker_order_id, status, filled_qty,"
            " fill_price, filled_at FROM orders WHERE mode = ? AND ts >= ?"
            " AND broker_order_id IS NOT NULL"
            f" AND (status IS NULL OR status NOT IN ({marks})) ORDER BY ts, id",
            (mode, since_ts, *sorted(TERMINAL_STATUSES)))
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def filled_orders(self, mode: str) -> list[dict]:
        """Every order of ``mode`` with a known fill, in fill order."""
        cur = self._conn.execute(FILLED_ORDERS_SQL, (mode,))
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def set_order_fill(self, order_id: int, status: OrderStatus) -> None:
        """Store the broker's word on one logged order."""
        self._conn.execute(
            "UPDATE orders SET status = ?, filled_qty = ?, fill_price = ?, filled_at = ?"
            " WHERE id = ?",
            (status.status, float(status.filled_qty), status.fill_price,
             status.filled_at.isoformat() if status.filled_at else None, int(order_id)))
        self._conn.commit()

    def record_equity(self, equity: float, cash: float, mode: str) -> None:
        self._conn.execute(
            "INSERT INTO equity_snapshots (ts, equity, cash, mode) VALUES (?, ?, ?, ?)",
            (utcnow().isoformat(), equity, cash, mode),
        )
        self._conn.commit()
