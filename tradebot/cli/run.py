"""`tradebot run` — the paper/live loop; `--dry-run`/`--replay` hand off to dryrun."""

from __future__ import annotations

import argparse

from .common import _load_settings, _resolve_universe
from .dryrun import _run_dry


def register(sub: argparse._SubParsersAction) -> None:
    r = sub.add_parser("run", help="run the paper/live/dry-run trading loop")
    r.add_argument("--config", default=None,
                   help="settings file (defaults to ./config.yaml when present)")
    r.add_argument("--once", action="store_true", help="single rebalance pass then exit")
    r.add_argument("--iterations", type=int, default=None, help="stop after N loops")
    r.add_argument(
        "--dry-run", dest="dry_run", action="store_true",
        help="forward-test: run the live loop with simulated fills against a "
             "virtual account; no orders are ever sent",
    )
    r.add_argument(
        "--replay", action="store_true",
        help="dry-run fully offline by replaying synthetic data (implies --dry-run, no creds)",
    )
    r.add_argument(
        "--replay-csv", dest="replay_csv",
        help="dry-run by replaying a local OHLCV CSV for the first symbol (implies --dry-run)",
    )
    r.add_argument(
        "--replay-periods", dest="replay_periods", type=int, default=500,
        help="number of synthetic bars to replay with --replay (default 500)",
    )
    r.add_argument(
        "--speed", type=float, default=0.0,
        help="seconds to sleep between replay steps (default 0 = as fast as possible)",
    )
    r.add_argument(
        "--autopilot", action="store_true",
        help="run the Autopilot headless: passes on poll_seconds inside market "
             "hours (every bar in a replay); --iterations caps the ticks",
    )
    r.add_argument(
        "--mode", choices=("off", "approve", "auto"), default="approve",
        help="autopilot mode: 'approve' parks each pass's trades for approval "
             "on the Autopilot page; 'auto' submits them; 'off' trades nothing "
             "and only sends the morning brief (default approve)",
    )
    r.set_defaults(func=cmd_run)


def _build_live_components(settings):
    from ..broker import get_broker
    from ..config import AlpacaCredentials
    from ..data import get_alpaca_data
    from ..risk import RiskManager
    from ..storage import Storage
    from ..strategies import build_strategy

    creds = AlpacaCredentials.from_env()
    if creds is None:
        raise SystemExit("Missing ALPACA_API_KEY / ALPACA_API_SECRET in environment/.env")
    broker = get_broker(creds.api_key, creds.api_secret, paper=settings.broker_is_paper)
    data = get_alpaca_data(creds.api_key, creds.api_secret, feed=creds.feed)
    strategy = build_strategy(settings.strategy_name, settings.strategy_params)
    risk = RiskManager(settings.risk)
    storage = Storage(settings.db_path)
    return broker, data, strategy, risk, storage


def _build_paper_engine(settings):
    """The paper/live engine exactly as ``run`` builds it (live stays gated)."""
    from ..engine import Engine

    broker, data, strategy, risk, storage = _build_live_components(settings)
    if settings.universe_name:
        storage.record_universe(settings.symbols, settings.mode)
    return Engine(settings, broker, data, strategy, risk, storage,
                  allocator=settings.build_allocator(),
                  selector=settings.build_selector(),
                  overlays=settings.build_overlays(),
                  notifier=settings.build_notifier())


def cmd_run(args: argparse.Namespace) -> int:
    settings = _load_settings(args, "run")

    # Replaying data only makes sense as a (offline) dry-run; imply the flag.
    if getattr(args, "replay", False) or getattr(args, "replay_csv", None):
        args.dry_run = True
    if getattr(args, "autopilot", False):
        from .autopilot import run_autopilot
        return run_autopilot(settings, args)
    if args.dry_run:
        return _run_dry(settings, args)

    if not _resolve_universe(settings):
        return 2
    engine = _build_paper_engine(settings)

    mode = "LIVE (real money)" if settings.is_live else "paper"
    print(f"Running in {mode} mode on {settings.symbols} with {engine.strategy.name}.")
    if args.once:
        for action in engine.rebalance():
            print(f"  {action.symbol}: target={action.target} order_qty={action.order_qty}")
    else:
        engine.run_forever(max_iterations=args.iterations)
    return 0
