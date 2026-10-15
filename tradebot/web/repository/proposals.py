"""Read-only access to the advisor's proposals and the order log behind them."""

from __future__ import annotations

import json

from ._db import _read


def latest_proposal(db_path: str, mode: str | None = None) -> dict | None:
    """The newest proposal batch with its lines, or None before the first one.
    Newest by time: a carried autopilot batch keeps its id but its latest time."""
    where, args = ("WHERE mode = ?", (mode,)) if mode else ("", ())
    head = _read(db_path, f"SELECT * FROM proposal_batches {where}"
                 " ORDER BY created_at DESC, id DESC LIMIT 1", args)
    if not head:
        return None
    out = head[0]
    try:
        out["provenance"] = json.loads(out.get("provenance") or "{}")
    except (json.JSONDecodeError, TypeError):
        out["provenance"] = {}
    out["lines"] = _read(db_path, "SELECT * FROM proposals WHERE batch_id = ? ORDER BY id",
                         (out["id"],))
    return out


def positions_from_orders(db_path: str, mode: str) -> dict[str, float]:
    """Signed quantity per symbol, summed over the order log for one mode.

    The offline stand-in for a broker's positions. The log records submitted
    orders, not fills, so this assumes every order filled in full, which is
    what the dry-run broker does. Flat symbols are left out.
    """
    rows = _read(
        db_path,
        "SELECT symbol, SUM(CASE WHEN side = 'buy' THEN qty ELSE -qty END) AS qty"
        " FROM orders WHERE mode = ? GROUP BY symbol ORDER BY symbol",
        (mode,),
    )
    return {r["symbol"]: float(r["qty"]) for r in rows if abs(r["qty"] or 0.0) > 1e-9}


def latest_equity(db_path: str, mode: str) -> dict | None:
    """The newest equity snapshot for one mode."""
    rows = _read(db_path, "SELECT ts, equity, cash, mode FROM equity_snapshots"
                 " WHERE mode = ? ORDER BY id DESC LIMIT 1", (mode,))
    return rows[0] if rows else None
