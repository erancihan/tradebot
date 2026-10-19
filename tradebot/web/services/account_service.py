"""Account snapshot: live Alpaca (read-only) when credentials exist, else the
last value recorded in the local SQLite log.

Network calls to Alpaca are wrapped defensively: the dashboard must never fail
to render because the broker is unreachable. A broker that fails is logged
once per process and named on the page, and the fallback is the paper
account's own snapshot (the broker read is always the paper endpoint), never
the newest snapshot of whichever account wrote last.
"""

from __future__ import annotations

import logging

from ..repository import TradingRepository

log = logging.getLogger("tradebot.web")

#: Shown beside a fallback after the broker failed.
BROKER_DOWN = "broker unavailable, showing the last recorded snapshot"
#: The account the dashboard's broker read is of.
BROKER_MODE = "paper"

#: The broker failure was logged already: once per process, not per poll.
_WARNED = False


def snapshot(repo: TradingRepository) -> dict:
    try:
        live = _try_live()
    except Exception as exc:  # noqa: BLE001 - never break the page on a broker hiccup
        _warn_once(exc)
        return _local(repo.latest_equity_for(BROKER_MODE), note=BROKER_DOWN)
    if live is not None:
        return live
    return _local(repo.latest_equity())


def _local(latest: dict | None, note: str | None = None) -> dict:
    if latest is None:
        return {"source": "none", "equity": None, "cash": None, "positions": [],
                "note": note}
    return {
        "source": "local",
        "equity": float(latest["equity"]),
        "cash": float(latest["cash"]),
        "mode": latest.get("mode", ""),
        "positions": [],  # positions aren't recorded locally; only available live
        "note": note,
    }


def _warn_once(exc: Exception) -> None:
    global _WARNED
    if not _WARNED:
        _WARNED = True
        log.warning("Account read from the broker failed; showing the last %s snapshot: "
                    "%s: %s", BROKER_MODE, type(exc).__name__, exc)


def _try_live() -> dict | None:
    """The paper account from Alpaca, None without credentials; a broker
    error propagates to :func:`snapshot`."""
    from ...config import AlpacaCredentials

    creds = AlpacaCredentials.from_env()
    if creds is None:
        return None
    from ...broker import get_broker

    broker = get_broker(creds.api_key, creds.api_secret, paper=True)
    acct = broker.account()
    positions = [
        {"symbol": s, "qty": p.qty, "avg_price": p.avg_price}
        for s, p in broker.positions().items()
    ]
    return {
        "source": "alpaca",
        "equity": acct.equity,
        "cash": acct.cash,
        "buying_power": acct.buying_power,
        "market_open": broker.is_market_open(),
        "positions": positions,
    }
