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


def selector_activity(frames, top_k: int = 2) -> float | None:
    """Fraction of live bars on which two different selectors disagree.

    A scenario where every selector picks the same names cannot distinguish
    them, so a verdict comparing selection mechanisms over it carries no
    information. Both prior gauntlets scored ~0 here and nobody noticed for
    months, which is why the number is now printed next to every result rather
    than living only in a test.
    """
    from ..selection import LowVolatilitySelector, MomentumSelector

    if not frames or len(frames) <= top_k:
        return 0.0
    try:
        momentum = MomentumSelector(lookback=60, skip=5, top_k=top_k)
        low_vol = LowVolatilitySelector(window=30, top_k=top_k)
        warmup = max(momentum.required_history, low_vol.required_history)
        mom = momentum.membership(frames).iloc[warmup:]
        lov = low_vol.membership(frames).iloc[warmup:]
        if mom.empty:
            return 0.0
        return float((mom != lov).any(axis=1).mean())
    except Exception:      # a diagnostic must never break the verdict
        return None


def _first_active(result) -> int:
    """Index of the first bar on which this contestant actually held anything.

    Detected from the curve rather than declared, because the gate is handed
    results, not pipelines: equity sits exactly at `initial_cash` while a
    contestant is still warming up.
    """
    curve = result.equity_curve
    moved = curve.to_numpy() != result.initial_cash
    return int(moved.argmax()) if moved.any() else 0


def _rebased(result, start: int) -> dict:
    """Return/CAGR/drawdown/worst-fold measured from bar ``start`` onward.

    This is the warmup fix. `buy_and_hold` is deployed from bar 1 while a
    60-bar momentum selector is flat for 61 bars, so comparing whole curves
    credits the baseline with returns earned while the candidate was not yet
    trading. `walkforward.py` already gives each fold a warmup prefix; the gate
    did not. Scoring both contestants from the bar where the *later* of the two
    starts is the cheapest honest fix available to something holding only
    curves.

    Note the direction of the correction is not knowable in advance: it removes
    whatever the market did during the warmup, which may favour either side.
    """
    curve = result.equity_curve.iloc[start:]
    if len(curve) < 2:
        curve = result.equity_curve
    first, last = float(curve.iloc[0]), float(curve.iloc[-1])
    total = last / first - 1.0 if first else 0.0
    years = len(curve) / (result.periods_per_year or 252.0)
    cagr = (last / first) ** (1.0 / years) - 1.0 if first > 0 and years > 0 else 0.0
    peak = curve.cummax()
    drawdown = float((curve / peak - 1.0).min())

    rets = curve.pct_change().dropna()
    folds = []
    n = len(rets)
    if n:
        k = max(1, min(4, n))
        edges = [round(i * n / k) for i in range(k + 1)]
        folds = [float((1.0 + rets.iloc[lo:hi]).prod() - 1.0)
                 for lo, hi in zip(edges, edges[1:]) if hi > lo]
    return {"total": total, "cagr": cagr, "drawdown": drawdown,
            "worst_fold": min(folds) if folds else 0.0}


def _activity_for(scenario_obj) -> float | None:
    """Selector activity for a Scenario; None when only a name was passed."""
    build = getattr(scenario_obj, "build_frames", None)
    if build is None:
        return None
    try:
        return selector_activity(build())
    except Exception:
        return None


def _overlapping_spans(ok_rows: list[dict]) -> list[tuple[str, str]]:
    """Pairs of scenarios that are partly the same underlying price path.

    Only meaningful for *provider* data. Generated scenarios (`synthetic`,
    `factor`) share a calendar by construction — they are drawn onto one epoch —
    while being different worlds, so comparing dates alone flags every generated
    pair as a duplicate. Scenarios carved from one pulled span genuinely are one
    path counted several times (the real pack nests two windows inside a third),
    and only there does the mean double-count.
    """
    import pandas as pd

    generated = (None, "synthetic", "factor")
    dated = [r for r in ok_rows
             if r.get("span") and r.get("source") not in generated]
    clashes = []
    for i, a in enumerate(dated):
        lo_a, hi_a = (pd.Timestamp(t) for t in a["span"])
        for b in dated[i + 1:]:
            lo_b, hi_b = (pd.Timestamp(t) for t in b["span"])
            shared = set(a.get("symbols") or ()) & set(b.get("symbols") or ())
            if not shared:
                continue
            overlap = (min(hi_a, hi_b) - max(lo_a, lo_b)).total_seconds()
            shortest = min((hi_a - lo_a).total_seconds(),
                           (hi_b - lo_b).total_seconds())
            # Judge *material* overlap, not any touch. Adjacent calendar-year
            # windows brush by a day or two at the boundary; that is not one
            # price path counted twice, which is the thing worth warning about.
            if shortest > 0 and overlap / shortest > 0.05:
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
    notes: list[str] = field(default_factory=list)   # diagnostics, not criteria

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
        for note in self.notes:
            lines.append(f"  ~ {note}")
        if self.notes:
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
        # Warmup discipline (M2): score both contestants from the bar where the
        # LATER of the two starts trading, so the baseline is not credited with
        # market moves the candidate was still warming up through.
        start = max(_first_active(cand.result), _first_active(base.result))
        c, b = _rebased(cand.result, start), _rebased(base.result, start)
        report.rows.append({
            "scenario": scenario_name, "ok": True,
            "warmup_bars": start,
            # Span of the *scored* window, not the raw data window. Real
            # scenarios extend their pull backward to cover warmup, so their
            # data windows overlap by construction while the periods they are
            # actually judged on do not — and it is the latter that would
            # double-count.
            "span": ((str(curve.index[start]), str(curve.index[-1]))
                     if start < len(curve) else None),
            "cand_return": c["total"],
            # Length-normalized, so windows of different lengths are
            # commensurable — see the aggregation note in `_return_check`.
            "cand_cagr": c["cagr"],
            "base_cagr": b["cagr"],
            "source": source, "symbols": symbols,
            "selector_active": _activity_for(scenario_obj),
            "cand_worst_fold": c["worst_fold"],
            "cand_max_drawdown": c["drawdown"],
            "base_return": b["total"],
            "base_worst_fold": b["worst_fold"],
            # Carried purely so the drawdown check can show what frame it is
            # judging in — see the M5 note there. Never used as a criterion.
            "base_max_drawdown": b["drawdown"],
            # Same comparison under other fold partitions, for the sensitivity
            # line. Computed here while both results are in hand.
            # Sensitivity is computed on the full curves: it asks whether the
            # fold *partition* drives the verdict, which is a separate question
            # from where scoring starts.
            "wf_wins_by_k": {
                k: min(fold_returns(cand.result, k)) >= min(fold_returns(base.result, k))
                for k in _SENSITIVITY_FOLDS
            },
        })

    ok_rows = [r for r in report.rows if r["ok"]]
    n = len(report.rows)
    report.checks.append(GateCheck(
        "completes every scenario", all_ok, f"{len(ok_rows)}/{n} clean"))

    # Degeneracy, reported next to the verdict rather than left for a post-mortem.
    trimmed = [(r["scenario"], r["warmup_bars"]) for r in ok_rows
               if r.get("warmup_bars")]
    if trimmed:
        report.notes.append(
            "scored post-warmup (bars dropped so both contestants are deployed): "
            + " ".join(f"{n}:{k}" for n, k in trimmed))

    active = [(r["scenario"], r["selector_active"]) for r in ok_rows
              if r.get("selector_active") is not None]
    if active:
        worst = min(a for _, a in active)
        summary = " ".join(f"{n}:{a:.0%}" for n, a in active)
        report.notes.append(
            ("selector active: " + summary)
            + ("" if worst >= 0.20 else
               "  <-- BELOW 20% somewhere: a selector is near-inert there, so "
               "that scenario cannot tell selection mechanisms apart"))

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

        # M5 (diagnostic half only). Three criteria are relative to the
        # baseline; this one is absolute. In a scenario where the baseline
        # itself breaches the limit, an absolute bound is measuring the
        # *scenario*, not the candidate — and the combination is close to
        # unsatisfiable for any long-only book. The frame mismatch used to be
        # invisible here, so a FAIL read as "the candidate is too risky" when it
        # sometimes meant "this regime is". The baseline's own drawdown is now
        # printed beside it, and the mismatch is named when it bites.
        #
        # The criterion is deliberately UNCHANGED. Making the bound relative
        # would convert a recorded FAIL (synthetic, by 1.38pp), and PLAN.md's
        # admissibility test disqualifies any change whose effect on the
        # candidate in flight is known in advance. That call is the owner's, and
        # it must be pre-registered and shipped alone.
        deepest = min(r["cand_max_drawdown"] for r in ok_rows)
        base_deepest = min(r["base_max_drawdown"] for r in ok_rows)
        detail = f"deepest {deepest:.2%} (baseline {base_deepest:.2%})"
        if base_deepest < -max_drawdown_limit:
            detail += (f" — NOTE: the baseline also breaches -{max_drawdown_limit:.0%}, "
                       "so this absolute bound is partly measuring the regime")
        report.checks.append(GateCheck(
            f"max drawdown never worse than -{max_drawdown_limit:.0%}",
            deepest >= -max_drawdown_limit, detail))

    return report
