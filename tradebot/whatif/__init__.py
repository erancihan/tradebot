"""What-if simulator: replay a past plan, with monthly contributions.

A plan is a set of symbols, a start date, starting cash and an optional
monthly contribution, run through the same :class:`~tradebot.backtest.Backtester`
as every other result. The money gain (final value minus all cash put in) is
the headline; the time-weighted metrics strip contributions out.
"""

from __future__ import annotations

from .plan import WhatIfPlan, WhatIfResult, monthly_cash_flows
from .run import run_whatif, whatif_risk

__all__ = ["WhatIfPlan", "WhatIfResult", "monthly_cash_flows", "run_whatif", "whatif_risk"]
