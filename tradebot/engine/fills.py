"""Fills: ask the broker what became of the orders the log holds.

The engine logs an order the moment the broker accepts it, at the price it
was sized at. Whether and at what price it filled arrives later, so open
orders (never asked, or last seen working) are asked again at three points:
the start of every autopilot pass, the Today refresh, and right after a
submission. Never from a page load. A reconcile never breaks its caller.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from ..models import utcnow

log = logging.getLogger("tradebot.fills")

#: How far back an order still counts as open: older ones are left alone.
LOOKBACK_DAYS = 7


def _row_changed(row: dict, status) -> bool:
    filled_at = status.filled_at.isoformat() if status.filled_at else None
    return (row.get("status"), row.get("filled_qty"), row.get("fill_price"),
            row.get("filled_at")) != (status.status, float(status.filled_qty),
                                      status.fill_price, filled_at)


#: A broker's filled quantity may exceed the logged one by this much (rounding).
QTY_TOLERANCE = 1e-6


def _overfilled(row: dict, status) -> bool:
    """More shares filled than the row ordered: the id names another order."""
    return float(status.filled_qty) > float(row["qty"]) + QTY_TOLERANCE


def reconcile_orders(broker, storage, mode: str, *, now: datetime | None = None,
                     lookback_days: int = LOOKBACK_DAYS) -> int:
    """Ask ``broker`` about each open order of ``mode``; returns rows changed.

    A broker answering None cannot report: nothing to do. One order whose
    lookup raises is logged and skipped; the rest still go."""
    if storage is None:
        return 0
    since = ((now or utcnow()) - timedelta(days=lookback_days)).isoformat()
    changed = 0
    for row in storage.open_orders(mode, since):
        try:
            status = broker.order_status(row["broker_order_id"])
            if status is None or not _row_changed(row, status):
                continue
            if _overfilled(row, status):
                log.warning("Order %s (%s) reports %s filled of %s ordered; not stored",
                            row["broker_order_id"], row["symbol"], status.filled_qty,
                            row["qty"])
                continue
            storage.set_order_fill(row["id"], status)
            changed += 1
        except Exception:  # noqa: BLE001 - one order must not hide the others
            log.exception("Fill check failed for order %s (%s)",
                          row["broker_order_id"], row["symbol"])
    return changed


def reconcile(engine, *, now: datetime | None = None,
              lookback_days: int = LOOKBACK_DAYS) -> int:
    """:func:`reconcile_orders` over the engine's broker, log and account."""
    return reconcile_orders(engine.broker, engine.storage, engine.mode, now=now,
                            lookback_days=lookback_days)


def reconcile_quietly(engine, *, now: datetime | None = None) -> int:
    """A reconcile that cannot raise, for a caller in the middle of a pass."""
    try:
        return reconcile(engine, now=now)
    except Exception:  # noqa: BLE001 - fills are bookkeeping, never a pass breaker
        log.exception("Fill reconcile failed; continuing")
        return 0
