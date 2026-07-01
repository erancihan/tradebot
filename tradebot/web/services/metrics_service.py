"""Derive summary performance metrics from a list of equity snapshots."""

from __future__ import annotations


def summarize(equity_rows: list[dict]) -> dict:
    """Compute headline stats for the stat cards.

    Returns a dict with ``present`` False when there is no data yet, so the
    template can show an empty state instead of zeros.
    """
    if not equity_rows:
        return {"present": False}

    equities = [float(r["equity"]) for r in equity_rows]
    start, current = equities[0], equities[-1]
    cash = float(equity_rows[-1].get("cash", 0.0))

    peak = equities[0]
    max_dd = 0.0
    for e in equities:
        peak = max(peak, e)
        if peak > 0:
            max_dd = min(max_dd, (e - peak) / peak)

    return {
        "present": True,
        "start_equity": round(start, 2),
        "current_equity": round(current, 2),
        "cash": round(cash, 2),
        "total_return": (current / start - 1.0) if start else 0.0,
        "max_drawdown": max_dd,
        "points": len(equities),
        "mode": equity_rows[-1].get("mode", ""),
    }
