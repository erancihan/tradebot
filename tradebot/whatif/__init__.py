"""What-if simulator: replay a past plan, with monthly contributions.

A plan is a set of symbols, a start date, starting cash and an optional
monthly contribution, run through the same :class:`~tradebot.backtest.Backtester`
as every other result. The money gain (final value minus all cash put in) is
the headline; the time-weighted metrics strip contributions out.
"""

from __future__ import annotations

from .compare import benchmark_plan, comparison
from .compare_many import StrategyComparison, compare_strategies, needs_configuration
from .plan import WhatIfPlan, WhatIfResult, monthly_cash_flows
from .run import (plan_backtester, plan_start, plan_window, run_plan, run_whatif,
                  warmup_bars, whatif_risk)

__all__ = [
    "StrategyComparison", "WhatIfPlan", "WhatIfResult", "benchmark_plan", "compare_strategies",
    "comparison", "monthly_cash_flows", "needs_configuration", "plan_backtester",
    "plan_start", "plan_window", "run_plan", "run_whatif", "warmup_bars", "whatif_risk",
]
