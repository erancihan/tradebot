"""Discover job: rank names the owner neither watches nor holds, then store them.

The pool is Alpaca's most-active screen when the server has credentials, else
every daily frame in the local cache; either way the result says which. Data
budget with credentials: one most-actives call, one asset list, one batched
~55-day bar request for the 100-name shortlist, then at most 20 survivors
pulled through ``BarCache`` (about 250 calendar days each, once; cached for
Today and What-if afterwards). Without credentials nothing leaves the machine.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone

log = logging.getLogger("tradebot.web.discover")

TIMEFRAME = "1day"
#: Daily bars each Alpaca-pool name needs: the momentum window plus headroom.
FETCH_BARS = 126 + 1 + 30


def _universe():
    """The Alpaca liquidity screen with its defaults (seam for offline tests)."""
    from ....universe import AlpacaLiquidityUniverse

    return AlpacaLiquidityUniverse()


def _alpaca_pool(cache, fetcher, now: datetime, failures: dict):
    """The pool and its frame loader; ``failures`` collects every failed fetch
    (``{"tried": n, "failed": n, "first_error": "ClassName"}``) so the run can
    say so, or refuse to store a ranking built from nothing."""
    pool = [str(r["symbol"]) for r in _universe().resolve_details()]
    start = now - timedelta(days=math.ceil(FETCH_BARS * 1.5) + 10)

    def frames_for(symbols: list[str]) -> dict:
        frames = {}
        for sym in symbols:
            failures["tried"] = failures.get("tried", 0) + 1
            try:
                frames[sym] = cache.get(sym, TIMEFRAME, start=start, end=now,
                                        fetcher=fetcher)
            except Exception as exc:  # noqa: BLE001 - one bad name never sinks the run
                log.warning("Discover skipped %s: %s", sym, exc)
                failures["failed"] = failures.get("failed", 0) + 1
                failures.setdefault("first_error", type(exc).__name__)
        return frames

    return pool, frames_for


def _check_failures(failures: dict) -> dict:
    """Provenance fields for failed fetches; every fetch failing is an error,
    so a dead connection never replaces a good stored run with an empty one."""
    failed = failures.get("failed", 0)
    if not failed:
        return {}
    if failed >= failures.get("tried", 0):
        raise RuntimeError(f"none of the {failed} candidate names could be fetched "
                           f"({failures['first_error']}); the last search is kept. "
                           "Try again later.")
    return {"failed": failed, "failed_error": failures["first_error"]}


def _cache_pool(cache, cache_dir: str):
    from ....universe.discover import cached_daily_symbols

    def frames_for(symbols: list[str]) -> dict:
        return {s: cache.load(s, TIMEFRAME) for s in symbols}

    return cached_daily_symbols(cache_dir), frames_for


def _excluded(settings, store, trading_db: str) -> list[str]:
    """The active list, the watchlist and every name currently held."""
    from .. import holdings_service, symbols_service

    held = holdings_service._book(settings, trading_db)[0]
    return sorted({*symbols_service.active_symbols(settings, store), *store.watchlist(),
                   *(s for s, qty in held.items() if qty)})


def _run_discover(params: dict) -> dict:
    from ....data.cache import BarCache
    from ....storage import Storage
    from ....universe.discover import discover
    from .. import advisor_service, symbols_service

    settings, trading_db = params["settings"], params["trading_db"]
    now = params.get("now") or datetime.now(timezone.utc)
    cache, failures = BarCache(params["cache_dir"]), {}
    if advisor_service._credentials() is not None:
        source = "alpaca"
        pool, frames_for = _alpaca_pool(cache, advisor_service.build_default_fetcher(),
                                        now, failures)
    else:
        source = "cache"
        pool, frames_for = _cache_pool(cache, params["cache_dir"])
        if not pool:
            raise RuntimeError("no cached daily bars to search and no Alpaca credentials "
                               "on the server. Pull some once with: tradebot data pull "
                               "--symbols SPY QQQ IWM --timeframe 1day")
    # Only names the watchlist can hold: a cache file like SYN_A is not a ticker.
    pool = [s for s in pool if symbols_service.SYMBOL_RE.match(s)]
    with Storage(trading_db) as store:
        exclude = _excluded(settings, store, trading_db)
        result = discover(frames_for, pool, exclude=exclude, as_of=now.date(),
                          source=source)
        provenance = {**result.provenance, **_check_failures(failures),
                      "computed_at": now.isoformat()}
        run_id = store.record_discover_run(source=source, as_of=provenance["as_of"],
                                           provenance=provenance, rows=result.row_dicts())
    return {"summary": {"run_id": run_id, "rows": len(result.rows), "source": source},
            "provenance": provenance}
