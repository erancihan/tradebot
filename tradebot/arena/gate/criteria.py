"""The gate criteria: one function per check, each over the clean rows.

Each returns a :class:`GateCheck` (or a note, for diagnostics that are reported
but never vote). ``evaluate_gate`` only decides which of them apply.
"""

from __future__ import annotations

from .measure import _SENSITIVITY_FOLDS, _overlapping_spans
from .report import GateCheck


def completes_check(ok_rows: list[dict], n: int, all_ok: bool) -> GateCheck:
    return GateCheck("completes every scenario", all_ok, f"{len(ok_rows)}/{n} clean")


def warmup_note(ok_rows: list[dict]) -> str | None:
    """Degeneracy, reported next to the verdict rather than left for a post-mortem."""
    trimmed = [(r["scenario"], r["warmup_bars"]) for r in ok_rows
               if r.get("warmup_bars")]
    if not trimmed:
        return None
    return ("scored post-warmup (bars dropped so both contestants are deployed): "
            + " ".join(f"{n}:{k}" for n, k in trimmed))


def activity_note(ok_rows: list[dict]) -> str | None:
    active = [(r["scenario"], r["selector_active"]) for r in ok_rows
              if r.get("selector_active") is not None]
    if not active:
        return None
    worst = min(a for _, a in active)
    summary = " ".join(f"{n}:{a:.0%}" for n, a in active)
    return (("selector active: " + summary)
            + ("" if worst >= 0.20 else
               "  <-- BELOW 20% somewhere: a selector is near-inert there, so "
               "that scenario cannot tell selection mechanisms apart"))


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


def worst_fold_check(ok_rows: list[dict]) -> GateCheck:
    """``worst_fold`` >= the baseline's in a strict majority of scenarios.

    The verdict uses k=4; the attached sensitivity line says whether that
    choice of partition is load-bearing.
    """
    wins = sum(1 for r in ok_rows
               if r["cand_worst_fold"] >= r["base_worst_fold"])
    need = len(ok_rows) // 2 + 1
    sensitivity = _fold_sensitivity(ok_rows)
    return GateCheck(
        "worst fold >= baseline in a majority",
        wins >= need,
        f"{wins}/{len(ok_rows)} scenarios (need {need}); "
        f"across k=3..8: {sensitivity}")


def absolute_drawdown_check(ok_rows: list[dict], max_drawdown_limit: float) -> GateCheck:
    """M5, part one: "is this catastrophic?" — the admission bound.

    The two drawdown criteria are deliberately kept SEPARATE. The original
    error was conflating them into one absolute number; they measure different
    things and belong to different decisions:

      absolute  "is this catastrophic?"            -> admission
      relative  "is this worse than holding?"      -> competitiveness

    Splitting them is what actually resolves M5; it is not a loosening. Both
    are required, so this can only ever turn a PASS into a FAIL — which is
    precisely what makes it admissible under PLAN.md's test (a change that
    makes the candidate in flight fail *harder*). The earlier proposal —
    replacing the absolute bound with `absolute OR relative` — would have
    converted the recorded synthetic FAIL and was rejected for exactly that
    reason. Do not re-propose it.
    """
    deepest = min(r["cand_max_drawdown"] for r in ok_rows)
    base_deepest = min(r["base_max_drawdown"] for r in ok_rows)
    detail = f"deepest {deepest:.2%} (baseline {base_deepest:.2%})"
    if base_deepest < -max_drawdown_limit:
        detail += (f" — NOTE: the baseline also breaches -{max_drawdown_limit:.0%} "
                   "here, so this bound is partly measuring the regime; the "
                   "relative check below is the commensurable one")
    return GateCheck(
        f"max drawdown never worse than -{max_drawdown_limit:.0%}",
        deepest >= -max_drawdown_limit, detail)


def relative_drawdown_check(ok_rows: list[dict], max_drawdown_limit: float):
    """M5, part two: drawdown >= baseline, where the absolute bound is confounded.

    Returns a :class:`GateCheck`, or a note string when it does not apply.

    SCOPED to the scenarios where the baseline itself breaches the limit. Two
    reasons, and the second is the one that bites:

    1. Where the baseline stays inside the bound, the absolute bound is doing
       its job and is the right test. Nothing to add.
    2. An unscoped version is UNSATISFIABLE against a defensive baseline. A
       flat, all-cash baseline takes zero drawdown, so no long-only candidate
       can ever match it — the same trivial optimum `worst_fold` has, and the
       same reason it is degenerate as a standalone metric. Scoping makes it
       inert exactly where it would be degenerate.

    Compared per scenario, never on the global minimum: the deepest candidate
    drawdown and the deepest baseline drawdown can come from different
    scenarios, and comparing across them compares nothing.
    """
    confounded = [r for r in ok_rows
                  if r["base_max_drawdown"] < -max_drawdown_limit]
    if not confounded:
        return ("relative drawdown check not applicable: the baseline stays "
                f"inside -{max_drawdown_limit:.0%} everywhere, so the absolute "
                "bound is measuring the candidate, not the regime")
    dd_wins = sum(1 for r in confounded
                  if r["cand_max_drawdown"] >= r["base_max_drawdown"])
    dd_need = len(confounded) // 2 + 1
    return GateCheck(
        "drawdown >= baseline where the absolute bound is confounded",
        dd_wins >= dd_need,
        f"{dd_wins}/{len(confounded)} such scenarios (need {dd_need})")
