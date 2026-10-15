"""`tradebot status` — account snapshot straight from the broker."""

from __future__ import annotations

import argparse
import sys


def register(sub: argparse._SubParsersAction) -> None:
    s = sub.add_parser("status", help="print broker account snapshot")
    s.add_argument("--config", default=None,
                   help="settings file (defaults to ./config.yaml when present)")
    s.set_defaults(func=cmd_status)


def cmd_status(args: argparse.Namespace) -> int:
    from ..broker import get_broker
    from ..config import AlpacaCredentials
    from .common import _load_settings

    settings = _load_settings(args, "status")
    creds = AlpacaCredentials.from_env()
    if creds is None:
        print("Missing Alpaca credentials.", file=sys.stderr)
        return 2
    broker = get_broker(creds.api_key, creds.api_secret, paper=settings.broker_is_paper)
    acct = broker.account()
    print(f"Account ({'paper' if acct.is_paper else 'LIVE'}):")
    print(f"  equity      : {acct.equity:,.2f}")
    print(f"  cash        : {acct.cash:,.2f}")
    print(f"  buying_power: {acct.buying_power:,.2f}")
    print(f"  market open : {broker.is_market_open()}")
    positions = broker.positions()
    if positions:
        print("Positions:")
        for sym, p in positions.items():
            print(f"  {sym:<6} qty={p.qty:>10.4f} avg={p.avg_price:.2f}")
    else:
        print("No open positions.")
    return 0
