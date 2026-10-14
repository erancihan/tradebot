"""``evaluate_gate``: score each scenario, then apply the criteria."""

from __future__ import annotations

from ..result import ContestantResult
from ..scoring import fold_returns
from . import criteria
from .measure import _SENSITIVITY_FOLDS, _activity_for, _first_active, _rebased
from .report import GateReport


def _find(outcome, name: str) -> ContestantResult | None:
    for e in outcome.leaderboard.entries:
        if e.name == name:
            return e
    return None


def _failed_row(scenario_name: str, cand, base, candidate: str, baseline: str) -> dict:
    who = candidate if not cand.ok else baseline
    failed = cand if not cand.ok else base
    return {
        "scenario": scenario_name, "ok": False,
        "error": f"{who}: {failed.status.upper()} {failed.error or ''}".strip(),
    }


def _scored_row(scenario_obj, scenario_name: str, cand, base) -> dict:
    curve = cand.result.equity_curve
    # Warmup discipline (M2): score both contestants from the bar where the
    # LATER of the two starts trading, so the baseline is not credited with
    # market moves the candidate was still warming up through.
    start = max(_first_active(cand.result), _first_active(base.result))
    c, b = _rebased(cand.result, start), _rebased(base.result, start)
    return {
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
        "source": getattr(scenario_obj, "source", None),
        "symbols": tuple(getattr(scenario_obj, "symbols", ()) or ()),
        "selector_active": _activity_for(scenario_obj),
        "cand_worst_fold": c["worst_fold"],
        "cand_max_drawdown": c["drawdown"],
        "base_return": b["total"],
        "base_worst_fold": b["worst_fold"],
        # Carried purely so the drawdown check can show what frame it is
        # judging in — see the M5 note there. Never used as a criterion.
        "base_max_drawdown": b["drawdown"],
        # Sensitivity is computed on the full curves: it asks whether the
        # fold *partition* drives the verdict, which is a separate question
        # from where scoring starts.
        "wf_wins_by_k": {
            k: min(fold_returns(cand.result, k)) >= min(fold_returns(base.result, k))
            for k in _SENSITIVITY_FOLDS
        },
    }


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
    report = GateReport(candidate, baseline, max_drawdown_limit)

    all_ok = True
    for scenario_obj, outcome in outcomes:
        scenario_name = getattr(scenario_obj, "name", scenario_obj)
        cand = _find(outcome, candidate)
        base = _find(outcome, baseline)
        if cand is None:
            raise ValueError(f"candidate {candidate!r} not in scenario {scenario_name!r}")
        if base is None:
            raise ValueError(f"baseline {baseline!r} not in scenario {scenario_name!r}")
        report.family = getattr(cand.contestant, "family", "") or candidate
        if not (cand.ok and cand.result is not None and base.ok and base.result is not None):
            all_ok = False
            report.rows.append(_failed_row(scenario_name, cand, base, candidate, baseline))
            continue
        report.rows.append(_scored_row(scenario_obj, scenario_name, cand, base))

    _apply_criteria(report, all_ok, max_drawdown_limit)
    return report


def _apply_criteria(report: GateReport, all_ok: bool, max_drawdown_limit: float) -> None:
    ok_rows = [r for r in report.rows if r["ok"]]
    report.checks.append(criteria.completes_check(ok_rows, len(report.rows), all_ok))
    for note in (criteria.warmup_note(ok_rows), criteria.activity_note(ok_rows)):
        if note is not None:
            report.notes.append(note)
    if not ok_rows:
        return
    report.checks.append(criteria._return_check(ok_rows))
    report.checks.append(criteria.worst_fold_check(ok_rows))
    report.checks.append(criteria.absolute_drawdown_check(ok_rows, max_drawdown_limit))
    relative = criteria.relative_drawdown_check(ok_rows, max_drawdown_limit)
    if isinstance(relative, str):
        report.notes.append(relative)
    else:
        report.checks.append(relative)
