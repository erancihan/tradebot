"""The promotion pass gate: is this algorithm ready for paper trading?

One leaderboard on one dataset proves nothing, so promotion is judged over a
*gauntlet* — the same candidate across several scenarios (the regime library),
always against a baseline (default ``buy_and_hold``: the do-nothing allocation
every idea must beat net of costs). The criteria are deliberately relative
where synthetic data makes absolutes meaningless:

1. **Completes everywhere** — an error or timeout in any scenario fails.
2. **Beats the baseline on average** — mean total return across the gauntlet.
3. **At least as robust in most regimes** — ``worst_fold`` >= the baseline's
   in a strict majority of scenarios (a crash fold can't hide).
4. **Drawdown in bounds** — max drawdown never worse than a limit (default
   -35%) in any scenario.

The verdict is advisory, not magic: it comes with the experiment journal's
attempt count for the candidate's family, because a gate passed on the 20th
try means much less than one passed on the 2nd.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .result import ContestantResult
from .scoring import get_scorer


@dataclass
class GateCheck:
    label: str
    passed: bool
    detail: str


@dataclass
class GateReport:
    candidate: str
    baseline: str
    max_drawdown_limit: float
    rows: list[dict] = field(default_factory=list)   # one per scenario
    checks: list[GateCheck] = field(default_factory=list)
    attempts: int | None = None                      # journal count, if known
    family: str | None = None

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(c.passed for c in self.checks)

    def table(self) -> str:
        head = (f"{'scenario':<18} {'cand ret':>9} {'cand wF':>8} {'cand DD':>8}   "
                f"{'base ret':>9} {'base wF':>8}")
        lines = [
            "",
            f"Pass gate — candidate {self.candidate!r} vs baseline "
            f"{self.baseline!r} over {len(self.rows)} scenario(s)",
            head,
            "-" * len(head),
        ]
        for r in self.rows:
            if r["ok"]:
                lines.append(
                    f"{r['scenario']:<18} {r['cand_return']:>9.2%} {r['cand_worst_fold']:>8.3f} "
                    f"{r['cand_max_drawdown']:>8.2%}   {r['base_return']:>9.2%} "
                    f"{r['base_worst_fold']:>8.3f}"
                )
            else:
                lines.append(f"{r['scenario']:<18} {r['error']}")
        lines.append("")
        lines.append("criteria:")
        for c in self.checks:
            lines.append(f"  [{'x' if c.passed else ' '}] {c.label:<42} {c.detail}")
        if self.attempts is not None:
            lines.append(
                f"  [!] journal: family {self.family!r} has {self.attempts} "
                "attempt(s) on record — discount the verdict accordingly"
            )
        lines.append("")
        lines.append(f"VERDICT: {'PASS' if self.passed else 'FAIL'}")
        if self.passed:
            lines.append(
                "Next: `tradebot backtest --walk-forward`, then promote to a "
                "replay dry-run and a paper season (see README runbook)."
            )
        lines.append("")
        return "\n".join(lines)


def _find(outcome, name: str) -> ContestantResult | None:
    for e in outcome.leaderboard.entries:
        if e.name == name:
            return e
    return None


def evaluate_gate(
    candidate: str,
    baseline: str,
    outcomes: list[tuple[str, object]],
    max_drawdown_limit: float = 0.35,
) -> GateReport:
    """Judge ``candidate`` against ``baseline`` over (scenario_name, outcome) pairs."""
    if not outcomes:
        raise ValueError("gate needs at least one scenario outcome")
    worst_fold = get_scorer("worst_fold")
    report = GateReport(candidate, baseline, max_drawdown_limit)

    all_ok = True
    for scenario_name, outcome in outcomes:
        cand = _find(outcome, candidate)
        base = _find(outcome, baseline)
        if cand is None:
            raise ValueError(f"candidate {candidate!r} not in scenario {scenario_name!r}")
        if base is None:
            raise ValueError(f"baseline {baseline!r} not in scenario {scenario_name!r}")
        report.family = getattr(cand.contestant, "family", "") or candidate
        if not (cand.ok and cand.result is not None and base.ok and base.result is not None):
            all_ok = False
            who = candidate if not cand.ok else baseline
            failed = cand if not cand.ok else base
            report.rows.append({
                "scenario": scenario_name, "ok": False,
                "error": f"{who}: {failed.status.upper()} {failed.error or ''}".strip(),
            })
            continue
        report.rows.append({
            "scenario": scenario_name, "ok": True,
            "cand_return": cand.total_return,
            "cand_worst_fold": worst_fold(cand.result),
            "cand_max_drawdown": cand.max_drawdown,
            "base_return": base.total_return,
            "base_worst_fold": worst_fold(base.result),
        })

    ok_rows = [r for r in report.rows if r["ok"]]
    n = len(report.rows)
    report.checks.append(GateCheck(
        "completes every scenario", all_ok, f"{len(ok_rows)}/{n} clean"))

    if ok_rows:
        cand_mean = sum(r["cand_return"] for r in ok_rows) / len(ok_rows)
        base_mean = sum(r["base_return"] for r in ok_rows) / len(ok_rows)
        report.checks.append(GateCheck(
            "beats baseline mean return (net of costs)",
            cand_mean > base_mean,
            f"cand {cand_mean:.2%} vs base {base_mean:.2%}"))

        wins = sum(1 for r in ok_rows
                   if r["cand_worst_fold"] >= r["base_worst_fold"])
        need = len(ok_rows) // 2 + 1
        report.checks.append(GateCheck(
            "worst fold >= baseline in a majority",
            wins >= need,
            f"{wins}/{len(ok_rows)} scenarios (need {need})"))

        deepest = min(r["cand_max_drawdown"] for r in ok_rows)
        report.checks.append(GateCheck(
            f"max drawdown never worse than -{max_drawdown_limit:.0%}",
            deepest >= -max_drawdown_limit,
            f"deepest {deepest:.2%}"))

    return report
