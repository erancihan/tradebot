"""The benchmark a plan is judged against, and the numbers on the result card."""

from __future__ import annotations

from dataclasses import replace

from ..backtest import BacktestResult
from .plan import WhatIfPlan


def benchmark_plan(plan: WhatIfPlan) -> WhatIfPlan:
    """Equal-weight buy and hold over the same symbols, money and dates.

    Only the decision rule changes, so any difference in the result is the
    plan's doing, not more cash or a different window. A single-index
    benchmark (SPY) would answer a different question and is not used here.
    """
    return replace(plan, strategy="buy_and_hold", strategy_params={},
                   allocation="equal", allocation_params={},
                   selector=None, selector_params={})


def comparison(result: BacktestResult, benchmark: BacktestResult) -> dict[str, float]:
    """Money first (what the person asked), then plan performance.

    ``cagr`` and ``max_drawdown`` are time-weighted, so contributions do not
    count as growth. ``vs_benchmark_pct`` compares final values, which is fair
    because both books received exactly the same cash on the same bars.
    """
    bench_final = benchmark.final_equity
    vs = result.final_equity / bench_final - 1.0 if bench_final > 0 else 0.0
    return {
        "final_value": round(result.final_equity, 2),
        "benchmark_final": round(bench_final, 2),
        "contributions": round(result.total_contributed, 2),
        "gain": round(result.money_gain, 2),
        "benchmark_gain": round(benchmark.money_gain, 2),
        "cagr": round(result.cagr, 4),
        "benchmark_cagr": round(benchmark.cagr, 4),
        "max_drawdown": round(result.max_drawdown, 4),
        "benchmark_max_drawdown": round(benchmark.max_drawdown, 4),
        "vs_benchmark_pct": round(vs, 4),
    }
