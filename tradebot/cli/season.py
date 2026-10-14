"""`tradebot arena season` — durable, resumable real-time league seasons.

Bookkeeping commands (create/list/standings) live here; the two that feed bars
into a season (seed/run) live in `season_run.py`.
"""

from __future__ import annotations

import argparse
import sys

from .common import _format_standings
from .season_run import cmd_season_run, cmd_season_seed


def register(asub: argparse._SubParsersAction) -> None:
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
    sc.add_argument("--isolation", choices=["process", "thread", "auto"], default="thread",
                    help="thread (default) is light but its timeout is SOFT — an "
                         "over-budget contestant leaks a busy thread every tick; "
                         "process makes the budget a hard kill (and sandboxes)")
    sc.add_argument("--time-budget", dest="time_budget", type=float, default=10.0,
                    help="per-contestant seconds per tick (default 10)")
    sc.add_argument("--db", default="season.db")
    sc.set_defaults(func=cmd_season_create)

    _register_after_create(aSsub)


def _register_after_create(aSsub: argparse._SubParsersAction) -> None:
    ss = aSsub.add_parser("seed", help="backfill real history so the field starts warmed up")
    ss.add_argument("season_id", type=int)
    ss.add_argument("--start", required=True, help="ISO date, inclusive")
    ss.add_argument("--end", required=True, help="ISO date")
    ss.add_argument("--cache-dir", dest="cache_dir", default="data/cache")
    ss.add_argument("--db", default="season.db")
    ss.set_defaults(func=cmd_season_seed)

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


def cmd_season_create(args: argparse.Namespace) -> int:
    from ..arena.season import Season, SeasonConfig, SeasonStore

    config = SeasonConfig(
        name=args.name, symbols=args.symbols, timeframe=args.timeframe,
        metric=args.score, algo_paths=args.algos,
        initial_cash=args.cash, max_position_pct=args.max_position,
        isolation=args.isolation, time_budget_s=args.time_budget,
    )
    with SeasonStore(args.db) as store:
        season = Season.create(store, config)
    print(f"Created season #{season.id} '{config.name}' "
          f"({', '.join(config.symbols)}, ranked by {config.metric}) in {args.db}")
    return 0


def cmd_season_list(args: argparse.Namespace) -> int:
    from ..arena.season import SeasonStore

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
    from ..arena.season import SeasonStore

    with SeasonStore(args.db) as store:
        snap = store.latest_standings(args.season_id)
        seeded = store.seeded_through(args.season_id)
    if snap is None:
        print(f"Season #{args.season_id} has no standings yet.", file=sys.stderr)
        return 1
    print(f"Season #{args.season_id} standings (step {snap.step}, {snap.timestamp[:19]}):")
    print(_format_standings(snap))
    if seeded:
        # Say it at the point of use, not only in a doc: a table built on
        # backfilled bars looks exactly like one earned live, and the window was
        # chosen after the fact.
        live = "none yet — everything here is backfilled"
        if snap.timestamp > seeded:
            live = f"live since {seeded[:10]}"
        print(f"\n  ~ seeded through {seeded[:10]}; {live}. Standings over "
              f"backfilled bars are\n    not a live-forward result.")
    return 0
