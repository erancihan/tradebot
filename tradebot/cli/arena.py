"""`tradebot arena` — the competition commands.

Owns the `arena` subparser; the other groups (league, season, gate, journal,
saved-run history) attach themselves to it from their own modules.
"""

from __future__ import annotations

import argparse
import sys

from . import arena_gate, arena_history, arena_journal, arena_league, season


def register(sub: argparse._SubParsersAction) -> None:
    arena = sub.add_parser("arena", help="run algorithm competitions")
    asub = arena.add_subparsers(dest="arena_command", required=True)

    al = asub.add_parser("list", help="discover & list contestants (no run)")
    al.add_argument("--algos", required=True, nargs="+", help="algo files and/or folders")
    al.add_argument("--isolation", choices=["process", "thread", "auto"], default="process",
                    help="process = import each file in a hardened child (default); "
                         "thread = import in this process (trusts the files)")
    al.add_argument("--time-budget", dest="time_budget", type=float, default=10.0,
                    help="per-file import budget in seconds (default 10)")
    al.set_defaults(func=cmd_arena_list)

    av = asub.add_parser("validate", help="smoke-test one algo file")
    av.add_argument("path", help="path to an algo .py file")
    av.set_defaults(func=cmd_arena_validate)

    _register_run(asub)
    # Registration order is the order `tradebot arena --help` lists them.
    for group in (arena_league, season, arena_gate, arena_journal, arena_history):
        group.register(asub)


def _register_run(asub: argparse._SubParsersAction) -> None:
    ar = asub.add_parser("run", help="run a tournament and print a leaderboard")
    ar.add_argument("--algos", required=True, nargs="+", help="algo files and/or folders")
    ar.add_argument("--scenario", help="scenario YAML (default: built-in synthetic)")
    ar.add_argument("--score", default="sharpe",
                    help="ranking metric: sharpe|total_return|cagr|calmar|"
                         "worst_fold|consistency (default sharpe)")
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
    ar.add_argument("--require-sandbox", dest="require_sandbox", action="store_true",
                    default=False,
                    help="fail a contestant outright when requested containment "
                         "cannot be enforced (default: run it and warn loudly). "
                         "Kernels in CI and unprivileged containers commonly "
                         "refuse a network namespace.")
    ar.add_argument("--seccomp", action="store_true", default=False,
                    help="adversarial tier: also install a seccomp filter denying "
                         "execve/execveat/ptrace (blocks subprocess/os.system); "
                         "process isolation only")
    ar.add_argument("--out", help="write the leaderboard to this JSON file")
    ar.add_argument("--save", action="store_true", help="persist this run to the arena DB")
    ar.add_argument("--no-journal", dest="journal", action="store_false", default=True,
                    help="skip the experiment journal (attempts are recorded by "
                         "default — the multiple-testing ledger)")
    ar.add_argument("--db", default="arena.db", help="arena results DB (default arena.db)")
    ar.set_defaults(func=cmd_arena_run)


def cmd_arena_list(args: argparse.Namespace) -> int:
    # A module body is contestant code: `list` imports it where `run` would,
    # in a hardened child, unless the caller asks for the trusting loader.
    from ..arena.loader import discover
    from ..arena.runner import default_runner

    runner = default_runner(args.time_budget, args.isolation)
    contestants, errors = getattr(runner, "discover", discover)(args.algos)
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
    from ..arena.scenario import Scenario
    from ..arena.tournament import run_tournament

    scenario = Scenario.from_yaml(args.scenario) if args.scenario else Scenario.default()
    outcome = run_tournament(
        args.algos, scenario, metric=args.score, time_budget_s=args.time_budget,
        isolation=args.isolation, cpu_seconds=args.cpu_seconds, memory_mb=args.memory_mb,
        harden=args.harden, seccomp=args.seccomp,
        require_sandbox=getattr(args, "require_sandbox", False),
    )
    print(outcome.leaderboard.table())
    for e in outcome.load_errors:
        print(f"  ! load error: {e.path}: {e.message}", file=sys.stderr)

    if args.save or args.journal:
        from ..arena.store import ArenaStore

        with ArenaStore(args.db) as store:
            run_id = None
            if args.save:
                run_id = store.record_run(scenario, args.score, outcome)
                print(f"Saved as run #{run_id} in {args.db}")
            if args.journal:
                n = store.record_attempts(scenario, args.score, outcome, run_id=run_id)
                print(f"Journaled {n} attempt(s) in {args.db} — "
                      "review with `tradebot arena journal`.")
    if args.out:
        _write_leaderboard_json(args.out, scenario, outcome)
    return 0


def _write_leaderboard_json(path: str, scenario, outcome) -> None:
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
    with open(path, "w") as fh:
        json.dump(payload, fh, indent=2)
    print(f"Results written to {path}")


def cmd_arena_validate(args: argparse.Namespace) -> int:
    """Import one algo file and smoke-test it on a tiny synthetic scenario."""
    from ..arena.scenario import Scenario
    from ..arena.tournament import run_tournament

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
