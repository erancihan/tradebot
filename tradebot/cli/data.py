"""`tradebot data` — market-data utilities (the local bar cache)."""

from __future__ import annotations

import argparse
import sys


def register(sub: argparse._SubParsersAction) -> None:
    data = sub.add_parser("data", help="market-data utilities")
    dsub = data.add_subparsers(dest="data_command", required=True)
    dp = dsub.add_parser("pull", help="download bars from Alpaca into the local cache")
    dp.add_argument("--symbols", required=True, nargs="+")
    dp.add_argument("--timeframe", default="1day")
    dp.add_argument("--start", help="ISO date, e.g. 2023-01-01")
    dp.add_argument("--end", help="ISO date, e.g. 2024-01-01")
    dp.add_argument("--cache-dir", dest="cache_dir", default="data/cache")
    dp.set_defaults(func=cmd_data_pull)


def cmd_data_pull(args: argparse.Namespace) -> int:
    """Pull bars from Alpaca into the local cache for offline/repeatable use."""
    from ..data.cache import BarCache, build_default_fetcher

    fetcher = build_default_fetcher()
    if fetcher is None:
        print("Missing ALPACA_API_KEY / ALPACA_API_SECRET in environment/.env",
              file=sys.stderr)
        return 2
    cache = BarCache(args.cache_dir)
    for symbol in args.symbols:
        df = cache.get(symbol, args.timeframe, args.start, args.end, fetcher)
        print(f"  {symbol}: {len(df)} bars -> {cache.path(symbol, args.timeframe)}")
    return 0
