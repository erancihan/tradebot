"""Read-only pages of the order log and the proposal batches, newest first.

Each page is keyed on the table's own id (``before_id``): ids only grow, so
a page boundary never moves when new rows arrive while someone scrolls.
"""

from __future__ import annotations

from ._db import _read


def _page_clause(mode: str, before_id: int | None) -> tuple[str, tuple]:
    if before_id is None:
        return "WHERE mode = ?", (mode,)
    return "WHERE mode = ? AND id < ?", (mode, int(before_id))


def orders_page(db_path: str, mode: str, before_id: int | None, limit: int) -> list[dict]:
    """Orders for one mode, newest first. ``SELECT *`` on purpose: this reader
    is read-only and must not migrate, so a log written before ``price``
    existed comes back without it (the page then shows the quantity only)."""
    where, args = _page_clause(mode, before_id)
    rows = _read(db_path, f"SELECT * FROM orders {where} ORDER BY id DESC LIMIT ?",
                 (*args, int(limit)))
    for row in rows:
        row.setdefault("price", None)
    return rows


def proposal_batches_page(db_path: str, mode: str, before_id: int | None,
                          limit: int) -> list[dict]:
    """Proposal batches for one mode, newest first, each with its lines."""
    where, args = _page_clause(mode, before_id)
    heads = _read(db_path, "SELECT id, created_at, mode, equity, cash FROM proposal_batches"
                  f" {where} ORDER BY id DESC LIMIT ?", (*args, int(limit)))
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
