"""`tradebot backtest` — a config against CSV or Alpaca data, optionally walk-forward."""

from __future__ import annotations

import argparse
import sys

from .common import _print_summary


def register(sub: argparse._SubParsersAction) -> None:
    b = sub.add_parser("backtest", help="backtest a config against CSV or Alpaca data")
    b.add_argument("--config", required=True)
    b.add_argument("--csv", help="backtest a single symbol from a local OHLCV CSV")
    b.add_argument("--symbol", help="symbol label when using --csv")
    b.add_argument("--lookback", type=int, default=365, help="days of history (Alpaca)")
    b.add_argument("--out", help="write equity curve CSV here")
    b.add_argument("--walk-forward", dest="walk_forward", type=int, default=None,
                   metavar="N",
                   help="evaluate over N independent contiguous folds instead of "
                        "one run (regime-robustness check)")
    b.set_defaults(func=cmd_backtest)


def cmd_backtest(args: argparse.Namespace) -> int:
    from ..backtest import Backtester
    from ..config import Settings
    from ..data.synthetic import load_csv
    from ..risk import RiskManager
    from ..strategies import build_strategy

    settings = Settings.from_yaml(args.config)
    strategy = build_strategy(settings.strategy_name, settings.strategy_params)
    risk = RiskManager(settings.risk)
    bt = Backtester(
        strategy, risk,
        initial_cash=settings.initial_cash,
        commission=settings.commission,
        slippage_bps=settings.slippage_bps,
        allocator=settings.build_allocator(),
        selector=settings.build_selector(),
        overlays=settings.build_overlays(),
    )

    if args.csv:
        data = {args.symbol or settings.symbols[0]: load_csv(args.csv)}
    else:
        # Pull history from Alpaca for each configured symbol.
        from ..config import AlpacaCredentials
        from ..data import get_alpaca_data

        creds = AlpacaCredentials.from_env()
        if creds is None:
            print("No Alpaca credentials found and no --csv given. "
                  "Set ALPACA_API_KEY/ALPACA_API_SECRET or pass --csv.", file=sys.stderr)
            return 2
        ds = get_alpaca_data(creds.api_key, creds.api_secret, feed=creds.feed)
        data = {s: ds.history(s, timeframe=settings.timeframe, lookback=args.lookback)
                for s in settings.symbols}

    if args.walk_forward:
        return _walk_forward(bt, data, args.walk_forward)

    result = bt.run(data)
    _print_summary(result.summary())
    if args.out:
        result.equity_curve.to_csv(args.out)
        print(f"Equity curve written to {args.out}")
    return 0


def _walk_forward(bt, data, folds: int) -> int:
    from ..walkforward import required_warmup, walk_forward

    try:
        wf = walk_forward(bt, data, folds=folds)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(f"\n=== Walk-forward ({folds} folds, "
          f"{required_warmup(bt)} warmup bars each) ===")
    print(wf.table())
    print("\nEach fold is evaluated independently, out-of-sample for the "
          "pipeline's decisions.\nDispersion across folds is the point: "
          "one great fold carrying the rest is a red flag.\n"
          "(If you tune settings until this table looks good, you are "
          "data-snooping — count your attempts.)")
    return 0
