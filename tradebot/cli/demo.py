"""`tradebot demo` — self-contained offline backtests, no creds, no network."""

from __future__ import annotations

import argparse

from .common import _print_summary


def register(sub: argparse._SubParsersAction) -> None:
    # Derive the choices from the registry so new strategies are reachable
    # without editing the CLI (keeps the demo command in sync with the package).
    from ..strategies import STRATEGIES
    strategy_names = sorted(STRATEGIES)

    d = sub.add_parser("demo", help="offline backtest on synthetic data (no creds)")
    d.add_argument("--strategy", default="sma_crossover", choices=strategy_names)
    d.add_argument("--portfolio", action="store_true",
                   help="showcase the portfolio stack: momentum top-K selection "
                        "+ inverse-vol weighting over a synthetic candidate pool")
    d.add_argument("--seed", type=int, default=42)
    d.set_defaults(func=cmd_demo)


def cmd_demo(args: argparse.Namespace) -> int:
    """Self-contained offline backtest — no creds, no network."""
    from ..backtest import Backtester
    from ..data.synthetic import synthetic_ohlcv
    from ..risk import RiskConfig, RiskManager
    from ..strategies import build_strategy

    if args.portfolio:
        return _demo_portfolio(args)

    df = synthetic_ohlcv(periods=750, drift=0.0005, volatility=0.012, seed=args.seed)
    strategy = build_strategy(
        args.strategy,
        {"fast": 20, "slow": 50} if args.strategy == "sma_crossover" else {},
    )
    bt = Backtester(strategy, RiskManager(RiskConfig(max_position_pct=0.95)), initial_cash=10_000.0)
    result = bt.run(df, symbol="DEMO")
    _print_summary(result.summary())
    print(f"(synthetic data, strategy={args.strategy}) — buy & hold for reference:")
    bh = df["close"].iloc[-1] / df["open"].iloc[0] - 1
    print(f"  buy & hold return: {round(bh, 4)}\n")
    return 0


def _demo_portfolio(args: argparse.Namespace) -> int:
    """Offline showcase of the portfolio stack: momentum top-K selection over a
    synthetic candidate pool, inverse-vol weighting, joint risk sizing."""
    from ..allocation import build_allocator
    from ..backtest import Backtester
    from ..data.synthetic import synthetic_ohlcv
    from ..risk import RiskConfig, RiskManager
    from ..selection import build_selector
    from ..strategies import build_strategy

    # A varied candidate pool: different drifts/vols so the ranking has teeth.
    pool = {
        f"SYN{i}": synthetic_ohlcv(
            periods=750, drift=drift, volatility=vol, seed=args.seed + i
        )
        for i, (drift, vol) in enumerate([
            (0.0012, 0.010), (0.0008, 0.020), (0.0004, 0.012),
            (0.0000, 0.015), (-0.0004, 0.018), (0.0010, 0.025),
        ])
    }
    selector = build_selector("momentum", {"lookback": 126, "skip": 10, "top_k": 3})
    allocator = build_allocator("inverse_vol", {"window": 63})
    risk = RiskManager(RiskConfig(max_position_pct=0.5, max_gross_exposure=1.0,
                                  allow_fractional=True, rebalance_band_pct=0.02))
    bt = Backtester(
        build_strategy("buy_and_hold"), risk, initial_cash=10_000.0,
        allocator=allocator, selector=selector,
    )
    result = bt.run(pool)
    _print_summary(result.summary())
    print("(synthetic 6-symbol pool — momentum top-3, inverse-vol weights, "
          "2% no-trade band)")
    print("equal-weight buy & hold of the whole pool for reference:")
    bh = sum(df["close"].iloc[-1] / df["open"].iloc[0] - 1 for df in pool.values()) / len(pool)
    print(f"  pool buy & hold return: {round(bh, 4)}\n")
    return 0
