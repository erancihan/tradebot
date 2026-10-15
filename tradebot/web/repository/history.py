"""Read-only pages of the order log and the proposal batches, newest first.

Each page is a keyset on ``(time, id)``, both descending (``before`` is the
last shown row's pair). Ids alone are not enough: a replay run restarts the
clock, so ids can rise while times fall, and the timeline is merged by time.
The id breaks ties, so a page boundary never moves when rows arrive.
"""

from __future__ import annotations

from ._db import _read


Cursor = tuple[str, int]
#: Order columns added after the table first shipped (``storage/schema.py``).
_LATE_COLUMNS = ("price", "status", "filled_qty", "fill_price", "filled_at")


def _page_clause(mode: str, ts_col: str, before: Cursor | None) -> tuple[str, tuple]:
    if before is None:
        return "WHERE mode = ?", (mode,)
    ts, row_id = str(before[0]), int(before[1])
    return (f"WHERE mode = ? AND ({ts_col} < ? OR ({ts_col} = ? AND id < ?))",
            (mode, ts, ts, row_id))


def orders_page(db_path: str, mode: str, before: Cursor | None, limit: int) -> list[dict]:
    """Orders for one mode, newest first. ``SELECT *`` on purpose: this reader
    is read-only and must not migrate, so a log written before ``price``
    existed comes back without it (the page then shows the quantity only),
    and one written before the fill columns comes back unasked ("submitted")."""
    where, args = _page_clause(mode, "ts", before)
    rows = _read(db_path, f"SELECT * FROM orders {where} ORDER BY ts DESC, id DESC LIMIT ?",
                 (*args, int(limit)))
    for row in rows:
        for column in _LATE_COLUMNS:
            row.setdefault(column, None)
    return rows


def proposal_batches_page(db_path: str, mode: str, before: Cursor | None,
                          limit: int) -> list[dict]:
    """Proposal batches for one mode, newest first, each with its lines."""
    where, args = _page_clause(mode, "created_at", before)
    heads = _read(db_path, "SELECT id, created_at, mode, equity, cash FROM proposal_batches"
                  f" {where} ORDER BY created_at DESC, id DESC LIMIT ?", (*args, int(limit)))
    if not heads:
        return []
    marks = ", ".join("?" for _ in heads)
    lines = _read(db_path,
                  "SELECT id, batch_id, symbol, action, order_qty, price, notional, reason,"
                  f" status FROM proposals WHERE batch_id IN ({marks}) ORDER BY id",
                  tuple(h["id"] for h in heads))
    by_batch: dict[int, list[dict]] = {h["id"]: [] for h in heads}
    for line in lines:
        by_batch[line["batch_id"]].append(line)
    for head in heads:
        head["lines"] = by_batch[head["id"]]
    return heads
