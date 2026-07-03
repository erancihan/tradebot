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
    allocator=None,           # optional tradebot.allocation.Allocator
    selector=None,            # optional tradebot.selection.Selector
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

    # Membership gate, precomputed exactly like the Backtester (selectors are
    # prefix-stable, so this equals recomputing on each growing window).
    member = None
    if selector is not None:
        member = selector.membership(aligned).shift(1).fillna(False)

    pf = Portfolio(cash=config.initial_cash)
    policy.reset()
    pending: dict[str, int] = {s: 0 for s in symbols}
    slip = config.slippage_bps / 10_000.0
    fractional = risk.config.allow_fractional
    equity_points: list[float] = []

    for i, ts in enumerate(common):
        close_prices = {s: float(closes[s].iloc[i]) for s in symbols}
        equity = pf.equity(close_prices)

        # 1) Execute the targets decided on the previous bar, at this bar's
        #    open — sized jointly, exactly like the Backtester.
        bar_targets: dict[str, int] = {}
        bar_prices: dict[str, float] = {}
        for s in symbols:
            price = float(opens[s].iloc[i])
            if not np.isfinite(price) or price <= 0:
                continue
            target = pending[s]
            if member is not None and not bool(member[s].iloc[i]):
                target = 0
            bar_targets[s] = target
            bar_prices[s] = price

        weights = None
        if allocator is not None:
            # Same one-bar discipline as targets: weights come from bars
            # strictly before the fill bar.
            history = {s: aligned[s].iloc[:i] for s in bar_targets}
            weights = allocator.weights(bar_targets, history)
        desired = risk.allocate(bar_targets, equity, bar_prices, weights)

        for s, want in desired.items():
            price = bar_prices[s]
            delta = risk.material_delta(want, pf.position(s).qty, price, equity)
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
