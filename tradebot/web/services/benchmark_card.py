"""History glue around ``benchmark.py``: the snapshots' window, the active
list, and the performance card's alpha cell.

The alpha compares like with like: the benchmark ends at the last close
every held name has, so the equity it is set against is the snapshot taken
by then (at or before that close, or after it while no session had opened
yet), never the newest snapshot when a name's cache stops early.
"""

from __future__ import annotations

from datetime import date, datetime

from ...market.us import ET, MARKET_CLOSE, next_open
from . import benchmark, symbols_service

#: The card names at most this many symbols, then "+N more".
SHOWN_SYMBOLS = 6
MIXED_ACCOUNTS = "pick one account to compare"


def for_snapshots(repo, settings, cache_dir: str, rows: list[dict]) -> dict | None:
    """The benchmark over equity snapshots ``rows`` (oldest first), starting
    from the first one's equity, for the list the autopilot trades. Rows of
    more than one account have no single starting equity: no benchmark."""
    if not rows:
        return None
    symbols = symbols_service.active_symbols(settings, repo)
    since = datetime.fromisoformat(rows[0]["ts"])
    if len({r["mode"] for r in rows}) > 1:
        return benchmark.unavailable(symbols, since, MIXED_ACCOUNTS)
    return benchmark.compare(cache_dir, symbols, float(rows[0]["equity"]), since,
                             datetime.fromisoformat(rows[-1]["ts"]))


def equity_through(rows: list[dict], until: date) -> float:
    """The equity of the newest snapshot that still reflects the ``until``
    close: taken at or before it, or after it but before the next open. The
    first snapshot when none is (the benchmark then ends at its own start)."""
    close = datetime.combine(until, MARKET_CLOSE, tzinfo=ET)
    cutoff = next_open(close)
    eligible = [r for r in rows
                if benchmark.as_utc(datetime.fromisoformat(r["ts"])) < cutoff]
    return float((eligible or rows[:1])[-1]["equity"])


def _absent(bench: dict | None) -> dict:
    return {"present": False, "note": bench["note"] if bench else None,
            "missing": bench["requested"] if bench else [],
            "pull_start": bench["pull_start"] if bench else None,
            "mixed": bool(bench) and bench["note"] == MIXED_ACCOUNTS}


def card(bench: dict | None, rows: list[dict]) -> dict:
    """The performance card's third cell: alpha against holding the list,
    both measured from the first snapshot to the benchmark's last close."""
    if bench is None or bench["series"] is None or not rows:
        return _absent(bench)
    start = float(rows[0]["equity"])
    now = float(bench["series"].iloc[-1])
    bench_pct = now / start - 1.0 if start else None
    until = date.fromisoformat(bench["until"])
    equity = equity_through(rows, until)
    pct = equity / start - 1.0 if start else None
    shown = bench["symbols"][:SHOWN_SYMBOLS]
    return {"present": True, "now": now, "pct": bench_pct, "equity_pct": pct,
            "alpha": pct - bench_pct if pct is not None and bench_pct is not None else None,
            "symbols": bench["symbols"], "shown": shown,
            "more": len(bench["symbols"]) - len(shown),
            "since": bench["since"], "until": bench["until"],
            "source": bench["source"], "note": bench["note"]}


__all__ = ["SHOWN_SYMBOLS", "card", "equity_through", "for_snapshots"]
