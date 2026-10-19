"""Forward-test plumbing behind `tradebot run --dry-run` / `--replay`.

Kept apart from `run.py` because the dry-run path builds its own data source,
broker and replay driver, none of which the paper/live path touches.
"""

from __future__ import annotations

import argparse
import sys

from .common import _resolve_universe


def _run_dry(settings, args: argparse.Namespace) -> int:
    """Forward-test: the real-time loop with simulated fills, no orders sent."""
    built = _build_dry_engine(settings, args)
    if built is None:
        return 2
    engine, data, broker, storage, replay = built
    src = "replay" if replay else "live data"
    print(
        f"[DRY-RUN] Forward-test ({src}) on {settings.symbols} with "
        f"{engine.strategy.name}; virtual ${settings.initial_cash:,.0f}, no orders sent."
    )
    _drive_dry(engine, data, broker, storage, args, replay)
    return 0


def _build_dry_engine(settings, args: argparse.Namespace):
    """(engine, data, broker, storage, replay) for a forward-test, or None
    after printing why the market data is unavailable."""
    from ..broker.dryrun import DryRunBroker
    from ..engine import Engine
    from ..risk import RiskManager
    from ..storage import Storage
    from ..strategies import build_strategy

    strategy = build_strategy(settings.strategy_name, settings.strategy_params)
    storage = Storage(settings.db_path)
    selector = settings.build_selector()
    replay = bool(args.replay or args.replay_csv)
    data = _dry_data(settings, strategy, storage, selector, args, replay)
    if data is None:
        storage.close()
        return None
    broker = DryRunBroker(
        data, timeframe=settings.timeframe, initial_cash=settings.initial_cash,
        slippage_bps=settings.slippage_bps, commission=settings.commission,
    )
    storage.record_account_start("dry_run")   # a fresh virtual account: History starts here
    engine = Engine(
        settings, broker, data, strategy, RiskManager(settings.risk), storage,
        mode_label="dry_run", enforce_live_ack=False,
        allocator=settings.build_allocator(), selector=selector,
        overlays=settings.build_overlays(), notifier=settings.build_notifier(),
    )
    return engine, data, broker, storage, replay


def _dry_data(settings, strategy, storage, selector, args, replay: bool):
    """The market-data source for a forward-test, or None after printing why not."""
    if replay:
        # Replay generates frames for the configured symbols; a screened
        # universe needs live data, so it does not apply here.
        if settings.universe_name:
            print("[DRY-RUN] `universe:` is ignored in replay mode "
                  "(no live data to screen); using the configured symbols.")
        return _build_replay_data(settings, strategy, args, selector=selector)

    from ..config import AlpacaCredentials
    from ..data import get_alpaca_data

    creds = AlpacaCredentials.from_env()
    if creds is None:
        print(
            "Dry-run needs market data. Either pass --replay for a fully "
            "offline forward-test, or set ALPACA_API_KEY/ALPACA_API_SECRET "
            "(a free, data-only key — no trading account is used).",
            file=sys.stderr,
        )
        return None
    if not _resolve_universe(settings):
        return None
    if settings.universe_name:
        storage.record_universe(settings.symbols, "dry_run")
    return get_alpaca_data(creds.api_key, creds.api_secret, feed=creds.feed)


def _drive_dry(engine, data, broker, storage, args, replay: bool) -> None:
    try:
        if replay:
            _drive_replay(engine, data, args)
        elif args.once:
            engine.rebalance()
        else:
            engine.run_forever(max_iterations=args.iterations)
    except KeyboardInterrupt:
        print("\n[DRY-RUN] Interrupted.")
    finally:
        _print_dryrun_summary(broker)
        storage.close()


def _build_replay_data(settings, strategy, args, selector=None):
    from ..data.replay import ReplayData
    from ..data.synthetic import load_csv, synthetic_ohlcv

    warmup = strategy.required_history + 2
    if selector is not None:
        warmup = max(warmup, selector.required_history + 2)
    if args.replay_csv:
        frames = {settings.symbols[0]: load_csv(args.replay_csv)}
    else:
        frames = {
            sym: synthetic_ohlcv(periods=args.replay_periods, seed=42 + i)
            for i, sym in enumerate(settings.symbols)
        }
    return ReplayData(frames, warmup=warmup)


def _drive_replay(engine, data, args) -> None:
    import time

    steps = 0
    while True:
        # The replay's "now" is its newest bar, so the daily-loss session
        # follows the tape rather than the wall clock.
        engine.rebalance(now=data.timestamp.to_pydatetime())
        steps += 1
        if args.iterations and steps >= args.iterations:
            break
        if not data.has_next():
            break
        data.advance()
        if args.speed:
            time.sleep(args.speed)


def _print_dryrun_summary(broker) -> None:
    print("\n=== Dry-run forward-test summary ===")
    for k, v in broker.summary().items():
        print(f"  {k:>16}: {v}")
    print()
