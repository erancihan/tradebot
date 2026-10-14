"""The Today page's data: the stored proposal, and the inputs for a new one.

``view`` reads the latest proposal for the page. ``build_inputs`` gathers what
``advisor.propose`` needs on the server: bars through ``BarCache`` (fetching
only when Alpaca credentials are in the server environment, per ADR 0001) and
account state from the paper broker, or from the SQLite log when offline.
Computing is a job (``jobs/proposal.py``), so the request returns at once.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from ...config import AlpacaCredentials
from ...data.cache import BarCache, build_default_fetcher
from ..repository import TradingRepository
from .jobs.frames import _pull_hint

#: Bars beyond the stack's longest warmup, so a signal is never computed on
#: the warmup's ragged edge.
LOOKBACK_HEADROOM = 30

#: How the account strip names where equity and cash came from.
ACCOUNT_LABELS = {
    "alpaca": "Alpaca",
    "log": "from log",
    "initial_cash": "starting cash",
}

CONFIG_HINT = "cp config.example.yaml config.yaml"


def view(repo: TradingRepository, settings, settings_path: str | None) -> dict:
    """Latest proposal for the server's mode, plus how to get started."""
    stored = repo.latest_proposal(mode=settings.mode)
    return {
        "configured": settings_path is not None,
        "config_hint": None if settings_path else CONFIG_HINT,
        "symbols": list(settings.symbols),
        "proposal": _shape(stored) if stored else None,
    }


def _shape(stored: dict) -> dict:
    created = datetime.fromisoformat(stored["created_at"])
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - created).total_seconds()
    source = (stored.get("provenance") or {}).get("account", "")
    label = ACCOUNT_LABELS.get(source, source or "unknown")
    return {
        "id": stored["id"],
        "created_at": created.isoformat(),
        "age_seconds": max(age, 0.0),
        "mode": stored["mode"],
        "equity": stored["equity"],
        "cash": stored["cash"],
        "account_label": f"{stored['mode']} ({label})",
        "provenance": stored.get("provenance") or {},
        "lines": stored["lines"],
    }


# --- inputs for a fresh proposal ------------------------------------------------

def _credentials() -> AlpacaCredentials | None:
    return AlpacaCredentials.from_env()


def _paper_broker(creds: AlpacaCredentials):
    """Always the paper endpoint: the web layer never reads a live account."""
    from ...broker import get_broker

    return get_broker(creds.api_key, creds.api_secret, paper=True)


def lookback_bars(components) -> int:
    """Bars the strategy window needs: the longest warmup plus headroom."""
    need = max((c.required_history for c in components if c is not None), default=1)
    return int(need) + LOOKBACK_HEADROOM


def build_inputs(settings, *, trading_db: str, cache_dir: str, lookback: int,
                 now: datetime | None = None) -> dict:
    """Keyword arguments for ``advisor.propose`` (minus the strategy stack)."""
    now = now or datetime.now(timezone.utc)
    creds = _credentials()
    fetcher = build_default_fetcher() if creds is not None else None
    frames, history = _frames(settings, cache_dir, lookback, fetcher, now)
    equity, cash, positions, account = _account(settings, trading_db, creds)
    firsts = [f.index.min() for f in frames.values()]
    lasts = [f.index.max() for f in frames.values()]
    provenance = {
        "source": "alpaca" if fetcher is not None else "cache",
        "account": account, "timeframe": settings.timeframe, "lookback": lookback,
        "bars": {s: int(len(f)) for s, f in frames.items()},
        "start": min(firsts).isoformat(), "end": max(lasts).isoformat(),
        "computed_at": now.isoformat(),
        "note": "raw/unadjusted daily bars; suggestions only, nothing was ordered",
    }
    return {"frames": frames, "selector_frames": history, "equity": equity,
            "cash": cash, "positions": positions, "provenance": provenance}


def _frames(settings, cache_dir, lookback, fetcher, now):
    """(strategy window, full cached history) per symbol.

    The selector gets the whole cached history: a ranked walk's verdict
    depends on where its frame starts, so a lookback-trimmed head would
    change who is selected.
    """
    cache, tf = BarCache(cache_dir), settings.timeframe
    # Calendar span for `lookback` trading days, with room for holidays.
    start = now - timedelta(days=math.ceil(lookback * 1.5) + 10)
    frames, history, missing = {}, {}, []
    for sym in settings.symbols:
        try:
            if fetcher is not None:
                cache.get(sym, tf, start=start, end=now, fetcher=fetcher)
            full = cache.get(sym, tf, fetcher=None)
        except RuntimeError:
            missing.append(sym)
            continue
        if len(full) < lookback - LOOKBACK_HEADROOM:
            missing.append(sym)
            continue
        history[sym], frames[sym] = full, full.iloc[-lookback:]
    if missing:
        hint = _pull_hint(" ".join(missing), tf, start.date().isoformat(),
                          now.date().isoformat())
        why = ("Alpaca returned too few" if fetcher is not None else
               "no Alpaca credentials on the server and not enough cached")
        raise RuntimeError(f"{why} bars for {', '.join(missing)} ({tf}). "
                           f"Pull once with: {hint}")
    return frames, history


def _account(settings, trading_db: str, creds):
    """(equity, cash, positions, source) from the paper broker, else starting cash."""
    if creds is not None:
        broker = _paper_broker(creds)
        acct = broker.account()
        positions = {s: float(p.qty) for s, p in broker.positions().items()}
        return float(acct.equity), float(acct.cash), positions, "alpaca"
    cash = float(settings.initial_cash)
    return cash, cash, {}, "initial_cash"
