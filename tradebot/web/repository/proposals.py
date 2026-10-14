"""Read-only access to the advisor's proposals and the order log behind them."""

from __future__ import annotations

import json

from ._db import _read


def latest_proposal(db_path: str, mode: str | None = None) -> dict | None:
    """The newest proposal batch with its lines, or None before the first one."""
    where, args = ("WHERE mode = ?", (mode,)) if mode else ("", ())
    head = _read(db_path,
                 f"SELECT * FROM proposal_batches {where} ORDER BY id DESC LIMIT 1", args)
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
