"""Run a what-if plan through the shared Backtester."""

from __future__ import annotations

import pandas as pd

from ..backtest import Backtester, BacktestResult
from ..backtest.steps import align_frames
from ..risk import RiskConfig, RiskManager
from .compare import benchmark_plan, comparison
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


def _bound(value: str | None, df: pd.DataFrame) -> pd.Timestamp | None:
    return pd.Timestamp(value, tz=df.index.tz) if value else None


def _window(plan: WhatIfPlan, frames: dict[str, pd.DataFrame],
            warmup: int = 0) -> dict[str, pd.DataFrame]:
    """Each symbol's bars from ``warmup`` rows before the plan's start (as many
    as the frame has, strictly before it) through its end."""
    missing = [s for s in plan.symbols if s not in frames]
    if missing:
        raise ValueError(f"no bars for {', '.join(missing)}")
    out = {}
    for sym in plan.symbols:
        df = frames[sym].loc[:_bound(plan.end, frames[sym])]
        start = _bound(plan.start, df)
        first = 0 if start is None else int(df.index.searchsorted(start, side="left"))
        out[sym] = df.iloc[max(0, first - warmup):]
    return out


def plan_start(plan: WhatIfPlan, window: dict[str, pd.DataFrame]) -> pd.Timestamp | None:
    """The plan's first bar bound: everything before it in ``window`` is warmup."""
    return _bound(plan.start, next(iter(window.values())))


def warmup_bars(plan: WhatIfPlan) -> int:
    """How many bars before the start the plan's stack needs to decide on it."""
    bt = plan_backtester(plan)
    parts = (bt.strategy, bt.selector, bt.allocator)
    return max((int(getattr(p, "required_history", 1)) for p in parts if p is not None),
               default=1)


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


def plan_window(plan: WhatIfPlan, frames: dict[str, pd.DataFrame], warmup: int = 0
                ) -> tuple[dict[str, pd.DataFrame], dict[pd.Timestamp, float]]:
    """The plan's bars (with ``warmup`` bars before its start) and its
    contribution schedule over the bars from the start, shared by every rule
    run on it.

    Computed once per plan, so a comparison of many decision rules replays
    each one over exactly the same bars and the same cash on the same days.
    """
    window = _window(plan, frames, warmup)
    common, _ = align_frames(window, "run a what-if")
    start = plan_start(plan, window)
    own = common if start is None else common[common >= start]
    return window, monthly_cash_flows(own, plan.monthly_contribution)


def run_plan(plan: WhatIfPlan, window: dict[str, pd.DataFrame], flows: dict, *,
             commission: float = 0.0, slippage_bps: float = 1.0) -> BacktestResult:
    """``plan`` over a ``plan_window``: the warmup is history, the result
    starts at the plan's start."""
    return plan_backtester(plan, commission=commission, slippage_bps=slippage_bps).run(
        window, cash_flows=flows, start=plan_start(plan, window))


def run_whatif(plan: WhatIfPlan, frames: dict[str, pd.DataFrame], *,
               commission: float = 0.0, slippage_bps: float = 1.0) -> WhatIfResult:
    """Replay ``plan`` and its benchmark over ``frames`` with the same contributions
    and the same first bar; the plan's stack warms up on the bars before it."""
    window, flows = plan_window(plan, frames, warmup_bars(plan))
    costs = {"commission": commission, "slippage_bps": slippage_bps}
    result = run_plan(plan, window, flows, **costs)
    bench = run_plan(benchmark_plan(plan), window, flows, **costs)
    return WhatIfResult(plan=result, benchmark=bench,
                        contributions=result.total_contributed,
                        comparison=comparison(result, bench))
