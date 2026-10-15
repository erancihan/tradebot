"""External cash flows (contributions) and the returns that ignore them.

A contribution raises equity without being a return. Every time-weighted
metric (return, CAGR, Sharpe, drawdown) must therefore strip flows out, or a
plan that saves 200 a month would look like a strategy that earns.
"""

from __future__ import annotations

import pandas as pd


def bar_cash_flows(cash_flows: dict | None, common: pd.DatetimeIndex) -> pd.Series | None:
    """Cash flows as one amount per aligned bar, or ``None`` for no flows.

    A flow stamped on a bar outside the aligned timeline is an error, not a
    rounding: dropping it would silently change how much money the plan had.
    """
    if cash_flows is None:
        return None
    flows = pd.Series(0.0, index=common, name="cash_flow")
    for ts, amount in cash_flows.items():
        ts = pd.Timestamp(ts)
        if ts not in flows.index:
            raise ValueError(f"cash flow on {ts} is not a bar of the aligned timeline")
        flows.loc[ts] += float(amount)
    return flows


def growth_index(equity: pd.Series, flows: pd.Series, initial_cash: float) -> pd.Series:
    """Time-weighted growth of one unit of money, flows removed.

    Each bar's return is ``equity_t / (equity_{t-1} + flow_t) - 1``. The
    Backtester adds a flow before the bar is sized and invests it at that
    bar's open, so the flow is part of the capital the bar's return is earned
    on. Subtracting it from the end instead (``(equity_t - flow_t) /
    equity_{t-1}``) credits the flow's own gain or loss to the old capital: a
    10000 contribution on a 100 book that falls 3% reads as a -300% bar. With
    no flows this is exactly ``equity / initial_cash``.
    """
    previous = equity.shift(1)
    previous.iloc[0] = initial_cash
    base = previous + flows
    ratio = equity / base.where(base > 0)
    return ratio.fillna(1.0).cumprod().rename("growth")
