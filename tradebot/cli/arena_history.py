"""`tradebot arena history|show` — browse tournaments saved with `arena run --save`."""

from __future__ import annotations

import argparse
import sys


def register(asub: argparse._SubParsersAction) -> None:
    ah = asub.add_parser("history", help="list past saved tournaments")
    ah.add_argument("--db", default="arena.db")
    ah.set_defaults(func=cmd_arena_history)

    ash = asub.add_parser("show", help="print a saved tournament's leaderboard")
    ash.add_argument("run_id", nargs="?", type=int, help="run id (default: latest)")
    ash.add_argument("--db", default="arena.db")
    ash.set_defaults(func=cmd_arena_show)


def cmd_arena_history(args: argparse.Namespace) -> int:
    from ..arena.store import ArenaStore

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
    from ..arena.store import ArenaStore

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
