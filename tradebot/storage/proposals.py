"""Proposals: the advisor's suggested trades, one batch per refresh or pass.

A batch header keeps equity, cash and provenance once per proposal, so an
empty proposal ("nothing to do today") is still a recorded, dated answer
rather than an absence that looks like "never computed".
"""

from __future__ import annotations

import json

#: ``expired``: a pending line the next autopilot pass replaced before anyone
#: approved it. It is never executed: the prices it was sized at have moved.
LINE_STATUSES = ("suggested", "pending", "approved", "rejected", "submitted", "expired")

_LINE_COLUMNS = ("symbol", "action", "target", "current_qty", "desired_qty",
                 "order_qty", "price", "notional", "weight", "reason")


class ProposalsMixin:
    """Proposal writes and reads over ``self._conn``."""

    def record_proposal(self, proposal, mode: str, status: str = "suggested", *,
                        hold_status: str | None = None) -> int:
        """Persist one proposal and its lines; returns the batch id.

        ``hold_status`` overrides ``status`` for lines with nothing to trade
        (a hold or a skipped symbol), so a pending batch keeps its holds for
        the record without asking anyone to approve doing nothing.
        """
        for given in (status, hold_status or status):
            if given not in LINE_STATUSES:
                raise ValueError(f"status must be one of {LINE_STATUSES}, got {given!r}")

        def line_status(line) -> str:
            idle = getattr(line, "skipped", False) or not line.order_qty
            return (hold_status or status) if idle else status

        created = proposal.created_at.isoformat()
        cur = self._conn.execute(
            "INSERT INTO proposal_batches (created_at, mode, equity, cash, provenance)"
            " VALUES (?, ?, ?, ?, ?)",
            (created, mode, float(proposal.equity), float(proposal.cash),
             json.dumps(proposal.provenance or {}, default=str)),
        )
        batch_id = int(cur.lastrowid)
        self._conn.executemany(
            "INSERT INTO proposals (batch_id, created_at, mode, status, "
            + ", ".join(_LINE_COLUMNS) + ") VALUES (?, ?, ?, ?, "
            + ", ".join("?" for _ in _LINE_COLUMNS) + ")",
            [(batch_id, created, mode, line_status(line),
              *(getattr(line, c) for c in _LINE_COLUMNS)) for line in proposal.lines],
        )
        self._conn.commit()
        return batch_id

    def latest_proposal(self, mode: str | None = None) -> dict | None:
        """The newest batch (optionally for one mode) with its lines, or None."""
        where, args = ("WHERE mode = ?", (mode,)) if mode else ("", ())
        head = self._conn.execute(
            f"SELECT * FROM proposal_batches {where} ORDER BY id DESC LIMIT 1", args,
        ).fetchone()
        if head is None:
            return None
        rows = self._conn.execute(
            "SELECT * FROM proposals WHERE batch_id = ? ORDER BY id", (head["id"],),
        ).fetchall()
        out = dict(head)
        out["provenance"] = json.loads(out["provenance"] or "{}")
        out["lines"] = [dict(r) for r in rows]
        return out

    def pending_lines(self, mode: str) -> list[dict]:
        """Lines waiting for the user's approval, oldest first."""
        rows = self._conn.execute(
            "SELECT * FROM proposals WHERE mode = ? AND status = 'pending' ORDER BY id",
            (mode,),
        ).fetchall()
        return [dict(r) for r in rows]

    def proposal_lines(self, ids: list[int], mode: str, status: str) -> list[dict]:
        """The given lines that still belong to ``mode`` and carry ``status``."""
        if not ids:
            return []
        marks = ", ".join("?" for _ in ids)
        rows = self._conn.execute(
            f"SELECT * FROM proposals WHERE id IN ({marks}) AND mode = ? AND status = ?"
            " ORDER BY id", (*(int(i) for i in ids), mode, status),
        ).fetchall()
        return [dict(r) for r in rows]

    def set_line_status(self, ids: list[int], status: str) -> None:
        if status not in LINE_STATUSES:
            raise ValueError(f"status must be one of {LINE_STATUSES}, got {status!r}")
        self._conn.executemany(
            "UPDATE proposals SET status = ? WHERE id = ?", [(status, int(i)) for i in ids],
        )
        self._conn.commit()
