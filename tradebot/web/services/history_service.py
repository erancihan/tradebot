"""History: what the bot has done and decided, for one account, newest first.

Two kinds of event share one timeline: an order the bot submitted and a
proposal batch (what the advisor suggested, and what became of each line).
Each table is paged on its own ``(time, id)`` keyset and the two are merged
by time, so the cursor is one ``(ts, id)`` pair per table; see ``events_page``.
"""

from __future__ import annotations

from urllib.parse import urlencode

from ...storage.proposals import LINE_STATUSES

PAGE_SIZE = 20
#: The snapshots the performance card and its chart cover (the /api/equity default).
EQUITY_WINDOW = 2000


def active_mode(repo, settings) -> str:
    """The account History shows: the newest snapshot's mode (as the dashboard
    does), else the configured mode, so a Today refresh before any pass shows."""
    return repo.default_mode() or settings.mode


def performance(repo, mode: str) -> dict:
    """Equity now against the first snapshot in the window."""
    rows = repo.equity_series(mode=mode, limit=EQUITY_WINDOW)
    if not rows:
        return {"present": False, "mode": mode}
    first, last = float(rows[0]["equity"]), float(rows[-1]["equity"])
    return {
        "present": True, "mode": mode, "points": len(rows),
        "start": first, "now": last, "change": last - first,
        "pct": (last / first - 1.0) if first else None,
        "since": rows[0]["ts"], "as_of": rows[-1]["ts"],
    }


def _order_event(row: dict) -> dict:
    price = row.get("price")
    qty = float(row["qty"])
    return {"kind": "order", "id": row["id"], "ts": row["ts"], "symbol": row["symbol"],
            "side": row["side"], "qty": qty, "price": price,
            "notional": qty * float(price) if price is not None else None}


def _batch_event(head: dict) -> dict:
    """A batch as one line: its trades by status; holds are only counted."""
    trades = [ln for ln in head["lines"] if ln["order_qty"]]
    counts = {s: sum(1 for ln in trades if ln["status"] == s) for s in LINE_STATUSES}
    return {"kind": "proposal", "id": head["id"], "ts": head["created_at"],
            "trades": trades, "holds": len(head["lines"]) - len(trades),
            "counts": {s: n for s, n in counts.items() if n}}


Cursor = tuple[str, int]
#: The query parameters that carry each table's cursor.
_KEYS = {"order": ("order_ts", "order_id"), "proposal": ("batch_ts", "batch_id")}


def events_page(repo, mode: str, before_order: Cursor | None = None,
                before_batch: Cursor | None = None, limit: int | None = None) -> dict:
    """One page of the merged timeline and the cursor for the next, or None.

    Each table gives ``limit + 1`` rows past its ``(ts, id)`` cursor, newest
    first; whatever is left over after taking the newest ``limit`` proves a
    next page exists. The rows shown from a table are a prefix of that table's
    order, so its next cursor is its last shown row and nothing is skipped.
    """
    limit = PAGE_SIZE if limit is None else limit
    orders = [_order_event(r) for r in repo.orders_page(mode, before_order, limit + 1)]
    batches = [_batch_event(h)
               for h in repo.proposal_batches_page(mode, before_batch, limit + 1)]
    merged = sorted(orders + batches, key=lambda e: (e["ts"], e["kind"], e["id"]),
                    reverse=True)
    shown = merged[:limit]
    if len(merged) <= limit:
        return {"events": shown, "next": None}
    cursor = {"order": before_order, "proposal": before_batch}
    for event in shown:                        # newest first: the last one wins
        cursor[event["kind"]] = (event["ts"], event["id"])
    return {"events": shown, "next": next_url(cursor)}


def next_url(cursor: dict) -> str:
    """The partial that serves the page after ``cursor`` (kind -> (ts, id))."""
    query: dict = {}
    for kind, pair in cursor.items():
        if pair is not None:
            ts_key, id_key = _KEYS[kind]
            query[ts_key], query[id_key] = pair
    return "/partials/history" + (f"?{urlencode(query)}" if query else "")


def parse_cursor(ts: str | None, row_id: int | None) -> Cursor | None:
    """A table's cursor from its two query parameters; half a pair is none."""
    return None if ts is None or row_id is None else (ts, int(row_id))


def view(repo, settings) -> dict:
    mode = active_mode(repo, settings)
    return {"mode": mode, "performance": performance(repo, mode),
            **events_page(repo, mode)}
