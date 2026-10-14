"""`tradebot arena season seed|run` — the commands that feed bars into a season."""

from __future__ import annotations

import argparse
import sys

from .common import _format_standings


def cmd_season_seed(args: argparse.Namespace) -> int:
    """Backfill real history into a season so the field starts warmed up.

    Bars come from the local cache, and from Alpaca only on a miss — so a season
    seeded once re-seeds offline forever, like every other cached path.
    """
    from ..arena.season import Season, SeasonStore, seed_season
    from ..data.cache import BarCache, build_default_fetcher

    cache = BarCache(args.cache_dir)
    fetcher = build_default_fetcher()
    with SeasonStore(args.db) as store:
        season = Season.load(store, args.season_id)
        frames = {}
        for symbol in season.config.symbols:
            try:
                df = cache.get(symbol, season.config.timeframe,
                               args.start, args.end, fetcher)
            except RuntimeError as exc:
                print(f"  {symbol}: {exc}", file=sys.stderr)
                return 2
            if len(df):
                frames[symbol] = df
            print(f"  {symbol}: {len(df)} bars")

        if not frames:
            print("No bars to seed. Pull them first: tradebot data pull "
                  "--symbols ... --start ... --end ...", file=sys.stderr)
            return 2
        written = seed_season(season, frames)
        boundary = store.seeded_through(season.id)

    print(f"\nSeeded season #{season.id} with {written} bars "
          f"across {len(frames)} symbols, through {boundary[:10]}.")
    print("Standings over seeded bars are BACKFILLED, not live-earned: the "
          "window was chosen\nafter the fact. `season standings` marks the "
          "boundary; keep the two claims apart.")
    return 0


def cmd_season_run(args: argparse.Namespace) -> int:
    from ..arena.season import ReplaySeasonFeed, Season, SeasonStore, run_season

    printer = lambda snap: print(_format_standings(snap))  # noqa: E731
    on_error = lambda exc: print(f"  ! tick error: {exc}", file=sys.stderr)  # noqa: E731

    with SeasonStore(args.db) as store:
        season = Season.load(store, args.season_id)
        if args.simulate:
            _simulate_daemon(season, args, printer, on_error)
        elif args.replay:
            print(f"Running season #{season.id} '{season.config.name}' (replay):")
            run_season(season, ReplaySeasonFeed(_replay_frames(season, args)),
                       max_ticks=args.max_ticks, pace_s=args.pace, stop_on_empty=True,
                       on_step=printer, supervise=True, on_error=on_error)
        else:
            return _live_daemon(season, args, printer, on_error)
    return 0


def _replay_frames(season, args: argparse.Namespace) -> dict:
    from ..data.synthetic import synthetic_ohlcv

    return {
        sym: synthetic_ohlcv(periods=args.replay_periods, seed=42 + i)
        for i, sym in enumerate(season.config.symbols)
    }


def _simulate_daemon(season, args: argparse.Namespace, printer, on_error) -> None:
    # Dry-run the real daemon offline: replay feed + a simulated
    # market-open clock + no-op sleep, exercising the gating/partial-bar/
    # supervision/persist path without creds or wall-clock waits.
    from datetime import datetime, timezone

    from ..arena.season import ReplaySeasonFeed, run_season_daemon

    frames = _replay_frames(season, args)
    open_dt = datetime(2024, 1, 3, 14, 30, tzinfo=timezone.utc)  # Wed 09:30 ET
    print(f"Running season #{season.id} '{season.config.name}' (simulated daemon):")
    run_season_daemon(season, ReplaySeasonFeed(frames), poll_seconds=0,
                      ignore_market_hours=args.ignore_market_hours,
                      max_ticks=args.max_ticks, stop_on_empty=True,
                      clock=lambda: open_dt, sleep=lambda s: None,
                      on_step=printer, on_error=on_error)


def _live_daemon(season, args: argparse.Namespace, printer, on_error) -> int:
    from ..arena.season import AlpacaSeasonFeed, run_season_daemon
    from ..config import AlpacaCredentials

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
