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
from .scoring import fold_returns, get_scorer

#: Fold counts the worst-fold comparison is re-run at, for the sensitivity line.
#: The verdict itself still uses the library default (4).
_SENSITIVITY_FOLDS = (3, 4, 5, 6, 7, 8)


def _overlapping_spans(ok_rows: list[dict]) -> list[tuple[str, str]]:
    """Pairs of scenarios that are partly the same underlying price path.

    Only meaningful for *provider* data. Two synthetic scenarios share the same
    calendar by construction (they are generated onto one epoch) while being
    entirely independent draws, so comparing dates alone flags every synthetic
    pair as a duplicate. Real scenarios carved from one pulled span — the real
    pack nests two windows inside a third — genuinely are one path counted
    several times, and only there does the mean double-count.
    """
    dated = [r for r in ok_rows
             if r.get("span") and r.get("source") not in (None, "synthetic")]
    clashes = []
    for i, a in enumerate(dated):
        lo_a, hi_a = a["span"]
        for b in dated[i + 1:]:
            lo_b, hi_b = b["span"]
            shared = set(a.get("symbols") or ()) & set(b.get("symbols") or ())
            if shared and lo_a <= hi_b and lo_b <= hi_a:
                clashes.append((a["scenario"], b["scenario"]))
    return clashes


def _return_check(ok_rows: list[dict]) -> GateCheck:
    """Does the candidate beat the baseline on return, in commensurable units?

    Judged on the mean **CAGR**, not the mean total return. Averaging total
    returns over windows of different lengths has no interpretation — a 647-bar
    window and a 270-bar window contribute equally while representing very
    different amounts of compounding. Length-normalizing is a units fix: it can
    make passing easier or harder, and which one is not known in advance.

    Overlapping windows are reported rather than silently reweighted. Scenarios
    carved from one span (the real pack nests two windows inside a third) make
    the mean count one path several times; de-duplicating them automatically
    would be a judgement about which window is canonical, which belongs to
    whoever writes the gauntlet.
    """
    cand = sum(r["cand_cagr"] for r in ok_rows) / len(ok_rows)
    base = sum(r["base_cagr"] for r in ok_rows) / len(ok_rows)
    detail = f"cand {cand:.2%} vs base {base:.2%} (mean CAGR)"
    clashes = _overlapping_spans(ok_rows)
    if clashes:
        pairs = ", ".join(f"{a}~{b}" for a, b in clashes[:3])
        more = "" if len(clashes) <= 3 else f" +{len(clashes) - 3} more"
        detail += f"; WINDOWS OVERLAP: {pairs}{more} — the mean double-counts"
    return GateCheck("beats baseline mean return (net of costs)", cand > base, detail)


def _fold_sensitivity(ok_rows: list[dict]) -> str:
    """How the worst-fold win count moves with the fold partition.

    ``worst_fold`` is ``min()`` over a partition of one realized curve — an
    order statistic of a small dependent sample, so it is maximally sensitive to
    where the boundaries fall. The fold count was an undeclared researcher
    degree of freedom baked in at 4; printing the count at other partitions
    makes it visible whether a verdict turns on that choice.
    """
    counts = []
    for k in _SENSITIVITY_FOLDS:
        wins = sum(1 for r in ok_rows if r.get("wf_wins_by_k", {}).get(k))
        counts.append(f"{k}:{wins}")
    return " ".join(counts)


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
    """Judge ``candidate`` against ``baseline`` over (scenario, outcome) pairs.

    Each pair's first element may be a bare scenario *name* or a ``Scenario``.
    Passing the object lets the aggregation see `source` and `symbols`, which is
    what distinguishes "two windows carved from one pulled price path" (the mean
    double-counts) from "two independent synthetic draws that merely share an
    epoch" (it does not).
    """
    if not outcomes:
        raise ValueError("gate needs at least one scenario outcome")
    worst_fold = get_scorer("worst_fold")
    report = GateReport(candidate, baseline, max_drawdown_limit)

    all_ok = True
    for scenario_obj, outcome in outcomes:
        scenario_name = getattr(scenario_obj, "name", scenario_obj)
        source = getattr(scenario_obj, "source", None)
        symbols = tuple(getattr(scenario_obj, "symbols", ()) or ())
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
        curve = cand.result.equity_curve
        report.rows.append({
            "scenario": scenario_name, "ok": True,
            "cand_return": cand.total_return,
            # Length-normalized, so windows of different lengths are
            # commensurable — see the aggregation note in `_return_check`.
            "cand_cagr": cand.result.cagr,
            "base_cagr": base.result.cagr,
            "span": (str(curve.index[0]), str(curve.index[-1])) if len(curve) else None,
            "source": source, "symbols": symbols,
            "cand_worst_fold": worst_fold(cand.result),
            "cand_max_drawdown": cand.max_drawdown,
            "base_return": base.total_return,
            "base_worst_fold": worst_fold(base.result),
            # Same comparison under other fold partitions, for the sensitivity
            # line. Computed here while both results are in hand.
            "wf_wins_by_k": {
                k: min(fold_returns(cand.result, k)) >= min(fold_returns(base.result, k))
                for k in _SENSITIVITY_FOLDS
            },
        })

    ok_rows = [r for r in report.rows if r["ok"]]
    n = len(report.rows)
    report.checks.append(GateCheck(
        "completes every scenario", all_ok, f"{len(ok_rows)}/{n} clean"))

    if ok_rows:
        report.checks.append(_return_check(ok_rows))

        wins = sum(1 for r in ok_rows
                   if r["cand_worst_fold"] >= r["base_worst_fold"])
        need = len(ok_rows) // 2 + 1
        # Report how the count moves with the fold partition. `worst_fold` is
        # min() over a partition of one realized curve — an order statistic of a
        # tiny dependent sample, so it is maximally sensitive to where the
        # boundaries land, and the fold count was an undeclared researcher
        # degree of freedom baked in at 4. The verdict still uses k=4; this line
        # says whether that choice is load-bearing.
        sensitivity = _fold_sensitivity(ok_rows)
        report.checks.append(GateCheck(
            "worst fold >= baseline in a majority",
            wins >= need,
            f"{wins}/{len(ok_rows)} scenarios (need {need}); "
            f"across k=3..8: {sensitivity}"))

        deepest = min(r["cand_max_drawdown"] for r in ok_rows)
        report.checks.append(GateCheck(
            f"max drawdown never worse than -{max_drawdown_limit:.0%}",
            deepest >= -max_drawdown_limit,
            f"deepest {deepest:.2%}"))

    return report
