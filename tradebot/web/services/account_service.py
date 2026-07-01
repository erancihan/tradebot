"""Account snapshot: live Alpaca (read-only) when credentials exist, else the
last value recorded in the local SQLite log.

Network calls to Alpaca are wrapped defensively — the dashboard must never fail
to render because the broker is unreachable.
"""

from __future__ import annotations

from ..repository import TradingRepository


def snapshot(repo: TradingRepository) -> dict:
    live = _try_live()
    if live is not None:
        return live

    latest = repo.latest_equity()
    if latest is None:
        return {"source": "none", "equity": None, "cash": None, "positions": []}
    return {
        "source": "local",
        "equity": float(latest["equity"]),
        "cash": float(latest["cash"]),
        "mode": latest.get("mode", ""),
        "positions": [],  # positions aren't recorded locally; only available live
    }


def _try_live() -> dict | None:
    try:
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
    except Exception:  # noqa: BLE001 - never break the page on a broker hiccup
        return None
