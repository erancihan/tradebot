"""Command-line entrypoint.

    tradebot backtest --config config.yaml [--plot out.csv]
    tradebot demo                         # offline backtest on synthetic data
    tradebot run --config config.yaml     # paper/live loop (needs Alpaca creds)
    tradebot status --config config.yaml  # account snapshot from the broker

Live trading additionally requires TRADEBOT_LIVE_CONFIRM=I_UNDERSTAND (see config).
"""

from __future__ import annotations

import argparse
import logging
import sys

from . import __version__


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )


def _print_summary(summary: dict) -> None:
    print("\n=== Backtest summary ===")
    for k, v in summary.items():
        print(f"  {k:>14}: {v}")
    print()


def cmd_demo(args: argparse.Namespace) -> int:
    """Self-contained offline backtest — no creds, no network."""
    from .backtest import Backtester
    from .data.synthetic import synthetic_ohlcv
    from .risk import RiskConfig, RiskManager
    from .strategies import build_strategy

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


def cmd_backtest(args: argparse.Namespace) -> int:
    from .backtest import Backtester
    from .config import Settings
    from .data.synthetic import load_csv
    from .risk import RiskManager
    from .strategies import build_strategy

    settings = Settings.from_yaml(args.config)
    strategy = build_strategy(settings.strategy_name, settings.strategy_params)
    risk = RiskManager(settings.risk)
    bt = Backtester(
        strategy, risk,
        initial_cash=settings.initial_cash,
        commission=settings.commission,
        slippage_bps=settings.slippage_bps,
    )

    if args.csv:
        data = {args.symbol or settings.symbols[0]: load_csv(args.csv)}
    else:
        # Pull history from Alpaca for each configured symbol.
        from .config import AlpacaCredentials
        from .data import get_alpaca_data

        creds = AlpacaCredentials.from_env()
        if creds is None:
            print("No Alpaca credentials found and no --csv given. "
                  "Set ALPACA_API_KEY/ALPACA_API_SECRET or pass --csv.", file=sys.stderr)
            return 2
        ds = get_alpaca_data(creds.api_key, creds.api_secret, feed=creds.feed)
        data = {s: ds.history(s, timeframe=settings.timeframe, lookback=args.lookback)
                for s in settings.symbols}

    result = bt.run(data)
    _print_summary(result.summary())
    if args.out:
        result.equity_curve.to_csv(args.out)
        print(f"Equity curve written to {args.out}")
    return 0


def _build_live_components(settings):
    from .config import AlpacaCredentials
    from .broker import get_broker
    from .data import get_alpaca_data
    from .risk import RiskManager
    from .storage import Storage
    from .strategies import build_strategy

    creds = AlpacaCredentials.from_env()
    if creds is None:
        raise SystemExit("Missing ALPACA_API_KEY / ALPACA_API_SECRET in environment/.env")
    broker = get_broker(creds.api_key, creds.api_secret, paper=settings.broker_is_paper)
    data = get_alpaca_data(creds.api_key, creds.api_secret, feed=creds.feed)
    strategy = build_strategy(settings.strategy_name, settings.strategy_params)
    risk = RiskManager(settings.risk)
    storage = Storage(settings.db_path)
    return broker, data, strategy, risk, storage


def cmd_run(args: argparse.Namespace) -> int:
    from .config import Settings
    from .engine import Engine

    settings = Settings.from_yaml(args.config)

    # Replaying data only makes sense as a (offline) dry-run; imply the flag.
    if getattr(args, "replay", False) or getattr(args, "replay_csv", None):
        args.dry_run = True
    if args.dry_run:
        return _run_dry(settings, args)

    broker, data, strategy, risk, storage = _build_live_components(settings)
    engine = Engine(settings, broker, data, strategy, risk, storage)

    mode = "LIVE (real money)" if settings.is_live else "paper"
    print(f"Running in {mode} mode on {settings.symbols} with {strategy.name}.")
    if args.once:
        for action in engine.rebalance():
            print(f"  {action.symbol}: target={action.target} order_qty={action.order_qty}")
    else:
        engine.run_forever(max_iterations=args.iterations)
    return 0


def _run_dry(settings, args: argparse.Namespace) -> int:
    """Forward-test: the real-time loop with simulated fills, no orders sent."""
    from .broker.dryrun import DryRunBroker
    from .engine import Engine
    from .risk import RiskManager
    from .storage import Storage
    from .strategies import build_strategy

    strategy = build_strategy(settings.strategy_name, settings.strategy_params)
    risk = RiskManager(settings.risk)
    storage = Storage(settings.db_path)

    replay = bool(args.replay or args.replay_csv)
    if replay:
        data = _build_replay_data(settings, strategy, args)
    else:
        from .config import AlpacaCredentials
        from .data import get_alpaca_data

        creds = AlpacaCredentials.from_env()
        if creds is None:
            print(
                "Dry-run needs market data. Either pass --replay for a fully "
                "offline forward-test, or set ALPACA_API_KEY/ALPACA_API_SECRET "
                "(a free, data-only key — no trading account is used).",
                file=sys.stderr,
            )
            return 2
        data = get_alpaca_data(creds.api_key, creds.api_secret, feed=creds.feed)

    broker = DryRunBroker(
        data,
        timeframe=settings.timeframe,
        initial_cash=settings.initial_cash,
        slippage_bps=settings.slippage_bps,
        commission=settings.commission,
    )
    engine = Engine(
        settings, broker, data, strategy, risk, storage,
        mode_label="dry_run", enforce_live_ack=False,
    )

    src = "replay" if replay else "live data"
    print(
        f"[DRY-RUN] Forward-test ({src}) on {settings.symbols} with "
        f"{strategy.name}; virtual ${settings.initial_cash:,.0f}, no orders sent."
    )
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
    return 0


def _build_replay_data(settings, strategy, args):
    from .data.replay import ReplayData
    from .data.synthetic import load_csv, synthetic_ohlcv

    warmup = strategy.required_history + 2
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
        engine.rebalance()
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


def cmd_status(args: argparse.Namespace) -> int:
    from .config import AlpacaCredentials, Settings
    from .broker import get_broker

    settings = Settings.from_yaml(args.config)
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


def cmd_arena_list(args: argparse.Namespace) -> int:
    from .arena.loader import discover

    contestants, errors = discover(args.algos)
    if not contestants:
        print("No contestants found.", file=sys.stderr)
    else:
        print(f"{'name':<20} {'kind':<11} {'author':<12} tags")
        print("-" * 60)
        for c in contestants:
            print(f"{c.name:<20} {c.kind:<11} {c.author:<12} {', '.join(c.tags)}")
    for e in errors:
        print(f"  ! load error: {e.path}: {e.message}", file=sys.stderr)
    return 0


def cmd_arena_run(args: argparse.Namespace) -> int:
    from .arena.scenario import Scenario
    from .arena.tournament import run_tournament

    scenario = Scenario.from_yaml(args.scenario) if args.scenario else Scenario.default()
    outcome = run_tournament(
        args.algos, scenario, metric=args.score, time_budget_s=args.time_budget,
        isolation=args.isolation, cpu_seconds=args.cpu_seconds, memory_mb=args.memory_mb,
        harden=args.harden, seccomp=args.seccomp,
    )
    print(outcome.leaderboard.table())
    for e in outcome.load_errors:
        print(f"  ! load error: {e.path}: {e.message}", file=sys.stderr)

    if args.save:
        from .arena.store import ArenaStore

        with ArenaStore(args.db) as store:
            run_id = store.record_run(scenario, args.score, outcome)
        print(f"Saved as run #{run_id} in {args.db}")

    if args.out:
        import json

        payload = {
            "metric": outcome.leaderboard.metric,
            "scenario": scenario.name,
            "entries": [
                {
                    "rank": r.rank, "name": r.name, "author": r.author, "kind": r.kind,
                    "status": r.status, "score": r.score,
                    "total_return": None if r.result is None else r.total_return,
                    "sharpe": None if r.result is None else r.sharpe,
                    "max_drawdown": None if r.result is None else r.max_drawdown,
                    "num_trades": r.num_trades, "error": r.error,
                }
                for r in outcome.leaderboard.entries
            ],
        }
        with open(args.out, "w") as fh:
            json.dump(payload, fh, indent=2)
        print(f"Results written to {args.out}")
    return 0


def cmd_arena_validate(args: argparse.Namespace) -> int:
    """Import one algo file and smoke-test it on a tiny synthetic scenario."""
    from .arena.scenario import Scenario
    from .arena.tournament import run_tournament

    scenario = Scenario(name="validate", periods=120, seed=1)
    outcome = run_tournament([args.path], scenario, metric="total_return")
    if not outcome.leaderboard.entries and not outcome.load_errors:
        print(f"No contestants registered in {args.path}", file=sys.stderr)
        return 1
    ok = True
    for r in outcome.leaderboard.entries:
        if r.ok:
            print(f"  OK    {r.name}: return={r.total_return:.2%}, trades={r.num_trades}")
        else:
            ok = False
            print(f"  FAIL  {r.name}: {r.status} - {r.error}", file=sys.stderr)
    for e in outcome.load_errors:
        ok = False
        print(f"  FAIL  {e.path}: {e.message}", file=sys.stderr)
    return 0 if ok else 1


def _format_standings(snap) -> str:
    parts = "  ".join(
        f"{s.rank}.{s.name}({s.total_return:+.1%})" for s in snap.standings
    )
    return f"[{snap.step:>2}/{snap.total_steps} {snap.timestamp[:10]}] {parts}"


def cmd_arena_league(args: argparse.Namespace) -> int:
    from .arena.league import run_league
    from .arena.scenario import Scenario

    scenario = Scenario.from_yaml(args.scenario) if args.scenario else Scenario.default()
    print(f"League season ({scenario.name}, ranked by {args.score}):")
    result = run_league(
        args.algos, scenario, metric=args.score, snapshots=args.snapshots,
        time_budget_s=args.time_budget, isolation=args.isolation,
        cpu_seconds=args.cpu_seconds, memory_mb=args.memory_mb, harden=args.harden,
        seccomp=args.seccomp,
        pace_s=args.pace, on_snapshot=lambda snap: print(_format_standings(snap)),
    )
    print(result.final.table())
    for e in result.load_errors:
        print(f"  ! load error: {e.path}: {e.message}", file=sys.stderr)
    return 0


def cmd_season_create(args: argparse.Namespace) -> int:
    from .arena.season import Season, SeasonConfig, SeasonStore

    config = SeasonConfig(
        name=args.name, symbols=args.symbols, timeframe=args.timeframe,
        metric=args.score, algo_paths=args.algos,
        initial_cash=args.cash, max_position_pct=args.max_position,
        isolation=args.isolation,
    )
    with SeasonStore(args.db) as store:
        season = Season.create(store, config)
    print(f"Created season #{season.id} '{config.name}' "
          f"({', '.join(config.symbols)}, ranked by {config.metric}) in {args.db}")
    return 0


def cmd_season_list(args: argparse.Namespace) -> int:
    from .arena.season import SeasonStore

    with SeasonStore(args.db) as store:
        seasons = store.list_seasons()
    if not seasons:
        print(f"No seasons in {args.db}.")
        return 0
    print(f"{'#':>3}  {'name':<16} {'symbols':<14} {'metric':<12} {'status':<10} updated")
    print("-" * 72)
    for s in seasons:
        print(f"{s['id']:>3}  {s['name']:<16} {s['symbols']:<14} {s['metric']:<12} "
              f"{s['status']:<10} {s['updated_at'][:19].replace('T', ' ')}")
    return 0


def cmd_season_standings(args: argparse.Namespace) -> int:
    from .arena.season import SeasonStore

    with SeasonStore(args.db) as store:
        snap = store.latest_standings(args.season_id)
    if snap is None:
        print(f"Season #{args.season_id} has no standings yet.", file=sys.stderr)
        return 1
    print(f"Season #{args.season_id} standings (step {snap.step}, {snap.timestamp[:19]}):")
    print(_format_standings(snap))
    return 0


def cmd_season_run(args: argparse.Namespace) -> int:
    from .arena.season import (
        ReplaySeasonFeed,
        Season,
        SeasonStore,
        run_season,
        run_season_daemon,
    )
    from .data.synthetic import synthetic_ohlcv

    printer = lambda snap: print(_format_standings(snap))  # noqa: E731
    on_error = lambda exc: print(f"  ! tick error: {exc}", file=sys.stderr)  # noqa: E731

    with SeasonStore(args.db) as store:
        season = Season.load(store, args.season_id)
        if args.simulate:
            # Dry-run the real daemon offline: replay feed + a simulated
            # market-open clock + no-op sleep, exercising the gating/partial-bar/
            # supervision/persist path without creds or wall-clock waits.
            from datetime import datetime, timezone

            from .arena.season import run_season_daemon
            frames = {
                sym: synthetic_ohlcv(periods=args.replay_periods, seed=42 + i)
                for i, sym in enumerate(season.config.symbols)
            }
            open_dt = datetime(2024, 1, 3, 14, 30, tzinfo=timezone.utc)  # Wed 09:30 ET
            print(f"Running season #{season.id} '{season.config.name}' (simulated daemon):")
            run_season_daemon(season, ReplaySeasonFeed(frames), poll_seconds=0,
                              ignore_market_hours=args.ignore_market_hours,
                              max_ticks=args.max_ticks, stop_on_empty=True,
                              clock=lambda: open_dt, sleep=lambda s: None,
                              on_step=printer, on_error=on_error)
        elif args.replay:
            frames = {
                sym: synthetic_ohlcv(periods=args.replay_periods, seed=42 + i)
                for i, sym in enumerate(season.config.symbols)
            }
            print(f"Running season #{season.id} '{season.config.name}' (replay):")
            run_season(season, ReplaySeasonFeed(frames), max_ticks=args.max_ticks,
                       pace_s=args.pace, stop_on_empty=True, on_step=printer,
                       supervise=True, on_error=on_error)
        else:
            from .config import AlpacaCredentials
            from .arena.season import AlpacaSeasonFeed

            creds = AlpacaCredentials.from_env()
            if creds is None:
                print("Live season needs Alpaca credentials, or pass --replay for an "
                      "offline season.", file=sys.stderr)
                return 2
            feed = AlpacaSeasonFeed(season.config.symbols, season.config.timeframe,
                                    creds.api_key, creds.api_secret, feed=creds.feed)
            gate = "ignoring market hours" if args.ignore_market_hours else "market-hours gated"
            print(f"Running season #{season.id} '{season.config.name}' (live daemon, {gate}):")
            run_season_daemon(season, feed, poll_seconds=args.poll_seconds,
                              ignore_market_hours=args.ignore_market_hours,
                              max_ticks=args.max_ticks, on_step=printer, on_error=on_error)
    return 0


def cmd_arena_history(args: argparse.Namespace) -> int:
    from .arena.store import ArenaStore

    with ArenaStore(args.db) as store:
        runs = store.list_runs()
    if not runs:
        print(f"No saved runs in {args.db}.")
        return 0
    print(f"{'#':>4}  {'when (UTC)':<19} {'scenario':<14} {'metric':<12} "
          f"{'n':>3}  winner")
    print("-" * 72)
    for r in runs:
        when = r["ts"][:19].replace("T", " ")   # YYYY-MM-DD HH:MM:SS
        print(f"{r['id']:>4}  {when:<19} {r['scenario']:<14} {r['metric']:<12} "
              f"{r['num_contestants']:>3}  {r['winner'] or '-'}")
    return 0


def cmd_arena_show(args: argparse.Namespace) -> int:
    from .arena.store import ArenaStore

    with ArenaStore(args.db) as store:
        run_id = args.run_id if args.run_id is not None else store.latest_run_id()
        if run_id is None:
            print(f"No saved runs in {args.db}.", file=sys.stderr)
            return 1
        table = store.render_run(run_id)
    if table is None:
        print(f"Run #{run_id} not found in {args.db}.", file=sys.stderr)
        return 1
    print(f"Run #{run_id}{table}")
    return 0


def cmd_data_pull(args: argparse.Namespace) -> int:
    """Pull bars from Alpaca into the local cache for offline/repeatable use."""
    from .data.cache import BarCache, build_default_fetcher

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


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tradebot", description="Lean Alpaca trading bot.")
    p.add_argument("--version", action="version", version=f"tradebot {__version__}")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = p.add_subparsers(dest="command", required=True)

    d = sub.add_parser("demo", help="offline backtest on synthetic data (no creds)")
    d.add_argument("--strategy", default="sma_crossover",
                   choices=["sma_crossover", "rsi_reversion"])
    d.add_argument("--seed", type=int, default=42)
    d.set_defaults(func=cmd_demo)

    b = sub.add_parser("backtest", help="backtest a config against CSV or Alpaca data")
    b.add_argument("--config", required=True)
    b.add_argument("--csv", help="backtest a single symbol from a local OHLCV CSV")
    b.add_argument("--symbol", help="symbol label when using --csv")
    b.add_argument("--lookback", type=int, default=365, help="days of history (Alpaca)")
    b.add_argument("--out", help="write equity curve CSV here")
    b.set_defaults(func=cmd_backtest)

    r = sub.add_parser("run", help="run the paper/live/dry-run trading loop")
    r.add_argument("--config", required=True)
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
    r.set_defaults(func=cmd_run)

    s = sub.add_parser("status", help="print broker account snapshot")
    s.add_argument("--config", required=True)
    s.set_defaults(func=cmd_status)

    arena = sub.add_parser("arena", help="run algorithm competitions")
    asub = arena.add_subparsers(dest="arena_command", required=True)

    al = asub.add_parser("list", help="discover & list contestants (no run)")
    al.add_argument("--algos", required=True, nargs="+", help="algo files and/or folders")
    al.set_defaults(func=cmd_arena_list)

    av = asub.add_parser("validate", help="smoke-test one algo file")
    av.add_argument("path", help="path to an algo .py file")
    av.set_defaults(func=cmd_arena_validate)

    ar = asub.add_parser("run", help="run a tournament and print a leaderboard")
    ar.add_argument("--algos", required=True, nargs="+", help="algo files and/or folders")
    ar.add_argument("--scenario", help="scenario YAML (default: built-in synthetic)")
    ar.add_argument("--score", default="sharpe",
                    help="ranking metric: sharpe|total_return|cagr|calmar (default sharpe)")
    ar.add_argument("--time-budget", dest="time_budget", type=float, default=10.0,
                    help="per-contestant wall-clock budget in seconds (default 10)")
    ar.add_argument("--isolation", choices=["process", "thread", "auto"], default="process",
                    help="process = hard timeout + CPU/mem limits, errors if 'fork' is "
                         "unavailable (default); thread = lightweight soft timeout; "
                         "auto = process if possible, else soft fallback")
    ar.add_argument("--cpu-seconds", dest="cpu_seconds", type=int, default=None,
                    help="hard CPU-time limit per contestant (process isolation)")
    ar.add_argument("--memory-mb", dest="memory_mb", type=int, default=None,
                    help="hard memory limit in MB per contestant (process isolation)")
    ar.add_argument("--no-harden", dest="harden", action="store_false", default=True,
                    help="disable the contestant sandbox (no-disk-writes / no-network); "
                         "hardening is ON by default for process isolation")
    ar.add_argument("--seccomp", action="store_true", default=False,
                    help="adversarial tier: also install a seccomp filter denying "
                         "execve/execveat/ptrace (blocks subprocess/os.system); "
                         "process isolation only")
    ar.add_argument("--out", help="write the leaderboard to this JSON file")
    ar.add_argument("--save", action="store_true", help="persist this run to the arena DB")
    ar.add_argument("--db", default="arena.db", help="arena results DB (default arena.db)")
    ar.set_defaults(func=cmd_arena_run)

    aL = asub.add_parser("league", help="run a league: standings evolve over a season")
    aL.add_argument("--algos", required=True, nargs="+", help="algo files and/or folders")
    aL.add_argument("--scenario", help="scenario YAML (default: built-in synthetic)")
    aL.add_argument("--score", default="sharpe",
                    help="ranking metric: sharpe|total_return|cagr|calmar (default sharpe)")
    aL.add_argument("--snapshots", type=int, default=10,
                    help="number of standings snapshots over the season (default 10)")
    aL.add_argument("--pace", type=float, default=0.0,
                    help="seconds between snapshots, to watch it unfold (default 0)")
    aL.add_argument("--time-budget", dest="time_budget", type=float, default=10.0)
    aL.add_argument("--isolation", choices=["process", "thread", "auto"], default="process")
    aL.add_argument("--cpu-seconds", dest="cpu_seconds", type=int, default=None)
    aL.add_argument("--memory-mb", dest="memory_mb", type=int, default=None)
    aL.add_argument("--no-harden", dest="harden", action="store_false", default=True,
                    help="disable the contestant sandbox; hardening is ON by default")
    aL.add_argument("--seccomp", action="store_true", default=False,
                    help="adversarial tier: also install a seccomp filter denying "
                         "execve/execveat/ptrace; process isolation only")
    aL.set_defaults(func=cmd_arena_league)

    aS = asub.add_parser("season", help="durable, resumable real-time league season")
    aSsub = aS.add_subparsers(dest="season_command", required=True)

    sc = aSsub.add_parser("create", help="create a new season")
    sc.add_argument("--name", required=True)
    sc.add_argument("--symbols", required=True, nargs="+")
    sc.add_argument("--algos", required=True, nargs="+")
    sc.add_argument("--timeframe", default="1day")
    sc.add_argument("--score", default="sharpe")
    sc.add_argument("--cash", type=float, default=10_000.0)
    sc.add_argument("--max-position", dest="max_position", type=float, default=0.95)
    sc.add_argument("--isolation", choices=["process", "thread", "auto"], default="thread")
    sc.add_argument("--db", default="season.db")
    sc.set_defaults(func=cmd_season_create)

    sl = aSsub.add_parser("list", help="list seasons")
    sl.add_argument("--db", default="season.db")
    sl.set_defaults(func=cmd_season_list)

    sst = aSsub.add_parser("standings", help="show a season's latest standings")
    sst.add_argument("season_id", type=int)
    sst.add_argument("--db", default="season.db")
    sst.set_defaults(func=cmd_season_standings)

    sr = aSsub.add_parser("run", help="advance a season from a feed (replay or live)")
    sr.add_argument("season_id", type=int)
    sr.add_argument("--db", default="season.db")
    sr.add_argument("--replay", action="store_true", help="drive offline with synthetic bars")
    sr.add_argument("--simulate", action="store_true",
                    help="dry-run the daemon offline (replay feed + simulated market clock)")
    sr.add_argument("--replay-periods", dest="replay_periods", type=int, default=250)
    sr.add_argument("--max-ticks", dest="max_ticks", type=int, default=None)
    sr.add_argument("--poll-seconds", dest="poll_seconds", type=float, default=60.0)
    sr.add_argument("--pace", type=float, default=0.0)
    sr.add_argument("--ignore-market-hours", dest="ignore_market_hours",
                    action="store_true", help="(live) step even when the market is closed")
    sr.set_defaults(func=cmd_season_run)

    ah = asub.add_parser("history", help="list past saved tournaments")
    ah.add_argument("--db", default="arena.db")
    ah.set_defaults(func=cmd_arena_history)

    ash = asub.add_parser("show", help="print a saved tournament's leaderboard")
    ash.add_argument("run_id", nargs="?", type=int, help="run id (default: latest)")
    ash.add_argument("--db", default="arena.db")
    ash.set_defaults(func=cmd_arena_show)

    data = sub.add_parser("data", help="market-data utilities")
    dsub = data.add_subparsers(dest="data_command", required=True)
    dp = dsub.add_parser("pull", help="download bars from Alpaca into the local cache")
    dp.add_argument("--symbols", required=True, nargs="+")
    dp.add_argument("--timeframe", default="1day")
    dp.add_argument("--start", help="ISO date, e.g. 2023-01-01")
    dp.add_argument("--end", help="ISO date, e.g. 2024-01-01")
    dp.add_argument("--cache-dir", dest="cache_dir", default="data/cache")
    dp.set_defaults(func=cmd_data_pull)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(getattr(args, "verbose", False))
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
