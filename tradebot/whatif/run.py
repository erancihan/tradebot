"""Run a what-if plan through the shared Backtester."""

from __future__ import annotations

import pandas as pd

from ..backtest import Backtester, BacktestResult
from ..backtest.steps import align_frames
from ..risk import RiskConfig, RiskManager
from .plan import WhatIfPlan, WhatIfResult, monthly_cash_flows

#: Drift trades smaller than this share of equity are skipped, so an
#: equal-weight book is not re-trimmed every bar; contributions accumulate
#: until they clear it. Full exits always execute (see RiskManager).
REBALANCE_BAND = 0.005


def whatif_risk() -> RiskManager:
    """A fully investable book: one name may hold everything, fractional shares.

    A person's plan is "put my money into these", so the 10% per-name default
    that guards the live bot would leave most of the cash idle and answer a
    different question.
    """
    return RiskManager(RiskConfig(max_position_pct=1.0, max_gross_exposure=1.0,
                                  allow_fractional=True,
                                  rebalance_band_pct=REBALANCE_BAND))


def _window(plan: WhatIfPlan, frames: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    missing = [s for s in plan.symbols if s not in frames]
    if missing:
        raise ValueError(f"no bars for {', '.join(missing)}")
    out = {}
    for sym in plan.symbols:
        df = frames[sym]
        start = pd.Timestamp(plan.start, tz=df.index.tz) if plan.start else None
        end = pd.Timestamp(plan.end, tz=df.index.tz) if plan.end else None
        out[sym] = df.loc[start:end]
    return out


def plan_backtester(plan: WhatIfPlan, *, commission: float = 0.0,
                    slippage_bps: float = 1.0) -> Backtester:
    """The plan's whole stack (strategy, selector, allocator) on one Backtester.

    Built from the same registries the config file uses, so a what-if plan is
    a portfolio the bot itself could run, not a separate model of one.
    """
    from ..allocation import build_allocator
    from ..selection import build_selector
    from ..strategies import build_strategy

    selector = (build_selector(plan.selector, plan.selector_params)
                if plan.selector else None)
    return Backtester(build_strategy(plan.strategy, plan.strategy_params), whatif_risk(),
                      initial_cash=plan.initial_cash, commission=commission,
                      slippage_bps=slippage_bps,
                      allocator=build_allocator(plan.allocation, plan.allocation_params),
                      selector=selector)


def run_whatif(plan: WhatIfPlan, frames: dict[str, pd.DataFrame], *,
               commission: float = 0.0, slippage_bps: float = 1.0) -> WhatIfResult:
    """Replay ``plan`` over ``frames`` with its monthly contributions."""
    window = _window(plan, frames)
    common, _ = align_frames(window, "run a what-if")
    flows = monthly_cash_flows(common, plan.monthly_contribution)
    result = plan_backtester(plan, commission=commission,
                             slippage_bps=slippage_bps).run(window, cash_flows=flows)
    comparison = {
        "final_value": round(result.final_equity, 2),
        "contributions": round(result.total_contributed, 2),
        "gain": round(result.money_gain, 2),
        "cagr": round(result.cagr, 4),
        "max_drawdown": round(result.max_drawdown, 4),
    }
    return WhatIfResult(plan=result, contributions=result.total_contributed,
                        comparison=comparison)
