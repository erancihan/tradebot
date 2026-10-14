"""The plan a person describes, the result they read, and the saving schedule."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from ..backtest import BacktestResult


@dataclass(frozen=True)
class WhatIfPlan:
    symbols: list[str]
    start: str                      # ISO date; the first bar at or after it starts the plan
    end: str | None
    initial_cash: float
    monthly_contribution: float = 0.0
    strategy: str = "buy_and_hold"
    strategy_params: dict = field(default_factory=dict)
    allocation: str = "equal"
    allocation_params: dict = field(default_factory=dict)
    selector: str | None = None
    selector_params: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.symbols:
            raise ValueError("a what-if plan needs at least one symbol")
        if self.initial_cash <= 0:
            raise ValueError(f"initial_cash must be positive, got {self.initial_cash}")
        if self.monthly_contribution < 0:
            raise ValueError("monthly_contribution cannot be negative")


@dataclass(frozen=True)
class WhatIfResult:
    plan: BacktestResult
    benchmark: BacktestResult        # equal-weight buy and hold, same cash flows
    contributions: float             # total cash put in, starting cash included
    comparison: dict[str, float]


def monthly_cash_flows(index: pd.DatetimeIndex, amount: float) -> dict[pd.Timestamp, float]:
    """``amount`` on the first bar of every calendar month after the first.

    The starting cash funds the first month, so bar 0 never gets a
    contribution, and a plan that starts mid-month gets no partial one. Each
    later month's first *bar* (not its first calendar day) receives the cash,
    so a month that opens on a weekend or holiday still contributes once.
    """
    if amount <= 0 or len(index) < 2:
        return {}
    months = [(ts.year, ts.month) for ts in index]
    return {
        index[i]: float(amount)
        for i in range(1, len(index))
        if months[i] != months[i - 1]
    }
