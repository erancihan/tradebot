"""Stepped, single-contestant simulation core.

Unlike the vectorised :class:`tradebot.backtest.Backtester` (which computes all
signals up front), this drives a ``Policy`` bar-by-bar — each step the policy
sees only a growing window of past+present data, so event-driven algos cannot
peek ahead. The execution/sizing rules are kept identical to the Backtester
(decide on bar *t*, fill on *t+1*'s open; same risk gates and slippage), and a
consistency test asserts the two agree for vectorised strategies.

Reuses Portfolio + RiskManager and returns a :class:`BacktestResult`, so all the
existing performance metrics apply unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..backtest import BacktestResult, _infer_periods_per_year
from ..portfolio import Portfolio
from ..risk import RiskManager
from .adapters import Policy


@dataclass(frozen=True)
class SimConfig:
    initial_cash: float = 10_000.0
    commission: float = 0.0
    slippage_bps: float = 1.0


def simulate(
    policy: Policy,
    frames: dict[str, pd.DataFrame],
    risk: RiskManager,
    config: SimConfig,
) -> BacktestResult:
    if not frames:
        raise ValueError("No data provided to simulate")

    # Align every symbol on a shared timeline (intersection of indices).
    common = None
    for df in frames.values():
        common = df.index if common is None else common.intersection(df.index)
    common = common.sort_values()
    if len(common) < 2:
        raise ValueError("Not enough overlapping bars to simulate")

    symbols = list(frames)
    aligned = {s: frames[s].reindex(common) for s in symbols}
    opens = {s: aligned[s]["open"] for s in symbols}
    closes = {s: aligned[s]["close"] for s in symbols}

    pf = Portfolio(cash=config.initial_cash)
    policy.reset()
    pending: dict[str, int] = {s: 0 for s in symbols}
    slip = config.slippage_bps / 10_000.0
    fractional = risk.config.allow_fractional
    equity_points: list[float] = []

    for i, ts in enumerate(common):
        close_prices = {s: float(closes[s].iloc[i]) for s in symbols}
        equity = pf.equity(close_prices)

        # 1) Execute the targets decided on the previous bar, at this bar's open.
        for s in symbols:
            price = float(opens[s].iloc[i])
            if not np.isfinite(price) or price <= 0:
                continue
            desired = risk.target_qty(pending[s], equity, price)
            current = pf.position(s).qty
            delta = desired - current

            if fractional:
                if abs(delta) < 1e-9:
                    continue
            else:
                delta = float(round(delta))
                if delta == 0:
                    continue

            increasing = (current == 0) or ((current > 0) == (delta > 0))
            if increasing:
                other_gross = pf.gross_exposure(close_prices, exclude=s)
                delta = risk.clamp_to_exposure(delta, price, equity, other_gross)
                if fractional:
                    if abs(delta) < 1e-9:
                        continue
                else:
                    delta = float(round(delta))
                    if delta == 0:
                        continue

            fill_price = price * (1 + slip) if delta > 0 else price * (1 - slip)
            pf.execute(s, delta, fill_price, commission=config.commission)

        equity_after = pf.equity(close_prices)

        # 2) Ask the policy for the next targets using data up to and incl. now.
        for s in symbols:
            window = aligned[s].iloc[: i + 1]
            pending[s] = policy.decide(s, window, pf.position(s), equity_after)

        equity_points.append(equity_after)

    curve = pd.Series(equity_points, index=common, name="equity")
    return BacktestResult(
        equity_curve=curve,
        trades=pf.trades,
        initial_cash=config.initial_cash,
        periods_per_year=_infer_periods_per_year(common),
    )
