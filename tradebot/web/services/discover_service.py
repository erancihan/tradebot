"""The Today page's Discover card: the newest stored ranking, and its pool.

The ranking itself is a job (``jobs/discover.py``); this only reads the last
run and marks the rows the owner has since put on the watchlist, so an "Add"
flips its row to "on watchlist" on the next render.
"""

from __future__ import annotations

from ..repository import TradingRepository
from . import advisor_service

POOL_HINTS = {
    "alpaca": "Alpaca's most-active names",
    "cache": "every symbol in your bar cache",
}


def view(repo: TradingRepository) -> dict:
    """``{run, pool_hint}``; ``run`` is None before the first search."""
    source = "alpaca" if advisor_service._credentials() is not None else "cache"
    run = repo.latest_discover_run()
    if run is not None:
        watched = set(repo.watchlist())
        run["rows"] = [{**r, "on_watchlist": r.get("symbol") in watched}
                       for r in run["rows"]]
    return {"run": run, "pool_hint": POOL_HINTS[source]}
