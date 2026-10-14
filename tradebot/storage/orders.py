"""Order and equity-snapshot records: the audit trail of what the bot did."""

from __future__ import annotations

from ..models import Order, utcnow


class OrdersMixin:
    """Order/equity writes over ``self._conn``."""

    def record_order(self, order: Order, broker_order_id: str | None, mode: str) -> None:
        self._conn.execute(
            "INSERT INTO orders (ts, symbol, side, qty, type, broker_order_id, mode)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                order.created_at.isoformat(),
                order.symbol,
                order.side.value,
                order.qty,
                order.type.value,
                broker_order_id,
                mode,
            ),
        )
        self._conn.commit()

    def record_equity(self, equity: float, cash: float, mode: str) -> None:
        self._conn.execute(
            "INSERT INTO equity_snapshots (ts, equity, cash, mode) VALUES (?, ?, ?, ?)",
            (utcnow().isoformat(), equity, cash, mode),
        )
        self._conn.commit()
