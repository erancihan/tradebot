"""Browser-triggered what-if job: a plan replayed with monthly contributions."""

from __future__ import annotations

from .frames import _equity_payload
from .frames_many import resolve_many


def _plan(params: dict, frames: dict):
    from ....whatif import WhatIfPlan

    first = next(iter(frames.values()))
    return WhatIfPlan(
        symbols=list(frames),
        start=params.get("start") or str(first.index.min().date()),
        end=params.get("end") or None,
        initial_cash=float(params.get("initial_cash", 10_000)),
        monthly_contribution=float(params.get("monthly_contribution") or 0.0),
        strategy=str(params.get("strategy") or "buy_and_hold"),
        strategy_params=dict(params.get("params") or {}),
        allocation=str(params.get("allocation") or "equal"),
        allocation_params=dict(params.get("allocation_params") or {}),
        selector=params.get("selector") or None,
        selector_params=dict(params.get("selector_params") or {}),
    )


def _run_whatif(params: dict) -> dict:
    from ....whatif import run_whatif

    frames, provenance = resolve_many(params)
    result = run_whatif(_plan(params, frames), frames)
    curve, bench = result.plan.equity_curve, result.benchmark.equity_curve
    return {
        "summary": dict(result.comparison),
        "equity": _equity_payload(curve.index, curve.to_numpy()),
        "benchmark": _equity_payload(bench.index, bench.to_numpy()),
        "provenance": provenance,
    }
