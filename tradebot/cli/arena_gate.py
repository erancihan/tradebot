"""`tradebot arena gate` — the promotion pass gate (exit code = verdict)."""

from __future__ import annotations

import argparse
import sys


def register(asub: argparse._SubParsersAction) -> None:
    ag = asub.add_parser("gate", help="promotion pass gate: candidate vs baseline "
                                      "over a scenario gauntlet (exit code = verdict)")
    ag.add_argument("--algos", required=True, nargs="+", help="algo files and/or folders")
    ag.add_argument("--candidate", required=True, help="contestant name to judge")
    ag.add_argument("--baseline", default="buy_and_hold",
                    help="benchmark contestant every idea must beat (default buy_and_hold)")
    ag.add_argument("--scenarios", required=True, nargs="+",
                    help="scenario YAMLs forming the gauntlet (use the regime library)")
    ag.add_argument("--max-drawdown", dest="max_drawdown", type=float, default=0.35,
                    help="fail if any scenario drawdown is worse than this (default 0.35)")
    ag.add_argument("--time-budget", dest="time_budget", type=float, default=10.0,
                    help="per-contestant wall-clock budget in seconds (default 10)")
    ag.add_argument("--seeds", type=int, default=1,
                    help="re-draw the whole gauntlet N times and take the median "
                         "verdict; flags UNSTABLE when the decision flips (a single "
                         "high-vol draw is not a reliable basis for a binary call)")
    ag.add_argument("--isolation", choices=["process", "thread", "auto"], default="process")
    ag.add_argument("--no-journal", dest="journal", action="store_false", default=True,
                    help="skip journaling the gauntlet runs as attempts")
    ag.add_argument("--db", default="arena.db", help="arena results DB (default arena.db)")
    ag.set_defaults(func=cmd_arena_gate)


def cmd_arena_gate(args: argparse.Namespace) -> int:
    """Promotion pass gate: judge one candidate against a baseline over a gauntlet."""
    seeds = max(1, int(getattr(args, "seeds", 1)))
    reports, all_runs = _run_gauntlets(args, seeds)
    report = reports[0] if seeds == 1 else _median_report(reports)
    _journal_gate(args, report, all_runs)

    print(report.table())
    if seeds > 1:
        passes = sum(1 for r in reports if r.passed)
        print(f"  seed ensemble: PASS in {passes}/{seeds} draws"
              + ("" if passes in (0, seeds) else "  <-- UNSTABLE, the verdict is noise"))
    return 0 if report.passed else 1


def _run_gauntlets(args: argparse.Namespace, seeds: int):
    """One gate report per seed, plus every (scenario, outcome) that fed them.

    A single synthetic draw is a weak basis for a binary decision: a high-vol
    window carries enough noise that the same scenario can resolve either way,
    so a one-path verdict is close to a coin flip on whether the effect it
    advertises is even present. Re-drawing the whole gauntlet and reporting the
    median — plus UNSTABLE when the verdict flips across draws — strips both
    lucky passes and unlucky fails, and it cannot be aimed at a candidate.
    """
    import dataclasses

    from ..arena.gate import evaluate_gate
    from ..arena.scenario import Scenario
    from ..arena.tournament import run_tournament

    base_scenarios = [Scenario.from_yaml(p) for p in args.scenarios]
    reports, all_runs = [], []
    for k in range(seeds):
        runs = []
        for base in base_scenarios:
            scenario = (base if k == 0
                        else dataclasses.replace(base, seed=base.seed + k))
            label = scenario.name if seeds == 1 else f"{scenario.name} (seed {scenario.seed})"
            print(f"  gauntlet: {label} ...", flush=True)
            outcome = run_tournament(
                args.algos, scenario, metric="worst_fold",
                time_budget_s=args.time_budget, isolation=args.isolation,
            )
            for e in outcome.load_errors:
                print(f"  ! load error: {e.path}: {e.message}", file=sys.stderr)
            runs.append((scenario, outcome))
        all_runs.extend(runs)
        reports.append(evaluate_gate(
            args.candidate, args.baseline,
            # Pass the Scenario, not just its name: the return aggregation needs
            # `source`/`symbols` to tell a genuinely duplicated price path from
            # two generated draws that merely share an epoch.
            [(sc, out) for sc, out in runs],
            max_drawdown_limit=args.max_drawdown))
    return reports, all_runs


def _journal_gate(args: argparse.Namespace, report, all_runs) -> None:
    from ..arena.store import ArenaStore, library_fingerprint

    fam = report.family or args.candidate
    with ArenaStore(args.db) as store:
        if args.journal:
            # Only the candidate's family: the rest of the field is run to
            # produce a baseline, not because anyone is iterating on it.
            for scenario, outcome in all_runs:
                store.record_attempts(scenario, "worst_fold", outcome,
                                      only_families={fam},
                                      library=library_fingerprint(args.scenarios))
        summary = {r["family"]: r for r in store.journal_summary()}
        if fam in summary:
            report.attempts = summary[fam]["attempts"]


def _median_report(reports):
    """Collapse per-seed gate reports into one, criterion by criterion.

    The median is taken per *criterion*, not over a summary score, so a
    candidate has to clear each bar in most draws rather than in a lucky one.
    A verdict that flips across seeds is reported as UNSTABLE by the caller
    rather than being silently resolved either way.
    """
    from statistics import median

    base = reports[0]
    for i, check in enumerate(base.checks):
        votes = [r.checks[i].passed for r in reports if i < len(r.checks)]
        check.passed = sum(votes) > len(votes) / 2
        check.detail = (f"{check.detail}  [{sum(votes)}/{len(votes)} seeds pass]")
    # Median the headline per-scenario numbers so the printed table is not just
    # the first draw pretending to be the ensemble.
    for row_idx, row in enumerate(base.rows):
        if not row.get("ok"):
            continue
        for key in ("cand_return", "base_return", "cand_cagr", "base_cagr",
                    "cand_worst_fold", "base_worst_fold", "cand_max_drawdown"):
            values = [r.rows[row_idx][key] for r in reports
                      if row_idx < len(r.rows) and r.rows[row_idx].get("ok") and key in r.rows[row_idx]]
            if values:
                row[key] = median(values)
    return base
