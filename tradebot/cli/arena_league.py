"""`tradebot arena league` — standings evolving over a replayed season."""

from __future__ import annotations

import argparse
import sys

from .common import _format_standings


def register(asub: argparse._SubParsersAction) -> None:
    aL = asub.add_parser("league", help="run a league: standings evolve over a season")
    aL.add_argument("--algos", required=True, nargs="+", help="algo files and/or folders")
    aL.add_argument("--scenario", help="scenario YAML (default: built-in synthetic)")
    aL.add_argument("--score", default="sharpe",
                    help="ranking metric: sharpe|total_return|cagr|calmar|"
                         "worst_fold|consistency (default sharpe)")
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


def cmd_arena_league(args: argparse.Namespace) -> int:
    from ..arena.league import run_league
    from ..arena.scenario import Scenario

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
