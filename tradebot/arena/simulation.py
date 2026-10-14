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

import pandas as pd

from ..backtest import BacktestResult
from ..backtest.steps import (
    _prepare_components,
    _sizing_marks,
    align_frames,
    book_weights,
    build_result,
    close_prices_at,
    fill_book,
    fillable_targets,
    shifted_membership,
)
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
    overlays=None,            # optional list of tradebot.overlays.Overlay
    on_decision=None,         # optional observer; see the call site below
) -> BacktestResult:
    if not frames:
        raise ValueError("No data provided to simulate")
    if overlays and allocator is None:
        raise ValueError("overlays require an allocator (they transform its weights)")
    overlays = list(overlays or [])

    common, aligned = align_frames(frames, "simulate")
    symbols = list(frames)
    _prepare_components(aligned, policy, allocator, selector, *overlays)
    opens = {s: aligned[s]["open"] for s in symbols}
    closes = {s: aligned[s]["close"] for s in symbols}
    member = shifted_membership(selector, aligned)

    pf = Portfolio(cash=config.initial_cash)
    policy.reset()
    pending: dict[str, int] = {s: 0 for s in symbols}
    slip = config.slippage_bps / 10_000.0
    equity_points: list[float] = []
    prev_closes: dict[str, float] = {}

    for i, ts in enumerate(common):
        close_prices = close_prices_at(closes, i)
        # 1) Execute the targets decided on the previous bar, at this bar's
        #    open — sized jointly, through the Backtester's own steps.
        bar_targets, bar_prices = fillable_targets(symbols, i, opens, pending.__getitem__, member)
        equity = pf.equity(_sizing_marks(symbols, bar_prices, prev_closes, close_prices))
        weights = book_weights(allocator, overlays, aligned, bar_targets, i)
        desired = risk.allocate(bar_targets, equity, bar_prices, weights)

        # Observer only — it must never influence the loop. This is the one
        # point where all three contestant kinds converge on a single shape
        # (signed quantities for the whole book), which is what makes a
        # consortium able to read every kind of member the same way.
        if on_decision is not None:
            on_decision(i, ts, dict(bar_targets), dict(desired), equity, dict(bar_prices))

        fill_book(pf, risk, desired, bar_prices, equity, slip, config.commission)
        equity_after = pf.equity(close_prices)
        prev_closes = close_prices

        # 2) Ask the policy for the next targets using data up to and incl. now.
        for s in symbols:
            window = aligned[s].iloc[: i + 1]
            pending[s] = policy.decide(s, window, pf.position(s), equity_after)
        equity_points.append(equity_after)

    return build_result(equity_points, common, pf, config.initial_cash)
