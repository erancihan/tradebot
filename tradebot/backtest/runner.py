"""Event-driven backtester.

Runs the *same* Strategy and RiskManager objects the live engine uses, so a
backtest exercises the real decision/sizing code. To avoid look-ahead bias,
targets computed from bar ``t``'s close are executed at bar ``t+1``'s open
(targets are shifted by one bar), with optional slippage and commission.
The *sizing* mark obeys the same discipline — see :func:`_sizing_marks`.

Supports a multi-symbol portfolio with shared cash; each symbol is sized
independently by the RiskManager and bounded by the gross-exposure cap.
"""

from __future__ import annotations

import pandas as pd

from ..portfolio import Portfolio
from ..risk import RiskManager
from ..strategies.base import Strategy
from .flows import bar_cash_flows
from .result import BacktestResult
from .steps import (
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


class Backtester:
    def __init__(
        self,
        strategy: Strategy,
        risk: RiskManager,
        initial_cash: float = 10_000.0,
        commission: float = 0.0,
        slippage_bps: float = 1.0,
        allocator=None,           # optional tradebot.allocation.Allocator
        selector=None,            # optional tradebot.selection.Selector
        overlays=None,            # optional list of tradebot.overlays.Overlay
    ) -> None:
        if overlays and allocator is None:
            raise ValueError("overlays require an allocator (they transform its weights)")
        self.strategy = strategy
        self.risk = risk
        self.initial_cash = initial_cash
        self.commission = commission
        self.slippage_bps = slippage_bps
        self.allocator = allocator
        self.selector = selector
        self.overlays = list(overlays or [])

    def run(
        self,
        data: dict[str, pd.DataFrame] | pd.DataFrame,
        symbol: str = "ASSET",
        cash_flows: dict[pd.Timestamp, float] | None = None,
        start: pd.Timestamp | None = None,
    ) -> BacktestResult:
        """Run the book over ``data``.

        ``cash_flows`` maps a bar timestamp to cash added to the book *before*
        that bar is sized, so a contribution is invested at that bar's open
        like any other cash. ``None`` (the default, and the arena's only mode)
        leaves the loop exactly as it was.

        ``start``: the bars strictly before it are warmup. The strategy,
        selector and allocator see them as history, but the book opens at the
        first bar at or after ``start`` and the result (equity, flows) begins
        there, so a plan is not left in cash while its indicators warm up.
        """
        if isinstance(data, pd.DataFrame):
            data = {symbol: data}
        if not data:
            raise ValueError("No data provided to backtest")

        common, aligned = align_frames(data, "backtest")
        _prepare_components(aligned, self.strategy, self.allocator, self.selector,
                            *self.overlays)
        targets = self._shifted_targets(aligned)
        opens = {s: aligned[s]["open"] for s in data}
        closes = {s: aligned[s]["close"] for s in data}
        member = shifted_membership(self.selector, aligned)
        first = _first_bar(common, start)
        flows = bar_cash_flows(cash_flows, common[first:])

        pf = Portfolio(cash=self.initial_cash)
        equity_points: list[float] = []
        slip = self.slippage_bps / 10_000.0
        # After a warmup the bar before the first is a printed close like any other.
        prev_closes = close_prices_at(closes, first - 1) if first else {}

        for i in range(first, len(common)):
            close_prices = close_prices_at(closes, i)
            if flows is not None:
                pf.cash += float(flows.iloc[i - first])
            # Gather this bar's fillable symbols, then size the book jointly so
            # the result never depends on symbol iteration order.
            bar_targets, bar_prices = fillable_targets(
                data, i, opens, lambda s: int(targets[s].iloc[i]), member)
            # Mark the book at prices already printed when we fill — never this
            # bar's close, which would size every fill with the return of the
            # bar it fills on. The close is still the right mark for the
            # reported equity point at the end of the bar.
            equity = pf.equity(_sizing_marks(data, bar_prices, prev_closes, close_prices))
            weights = book_weights(self.allocator, self.overlays, aligned, bar_targets, i)
            desired = self.risk.allocate(bar_targets, equity, bar_prices, weights)
            fill_book(pf, self.risk, desired, bar_prices, equity, slip, self.commission)
            equity_points.append(pf.equity(close_prices))
            prev_closes = close_prices

        return build_result(equity_points, common[first:], pf, self.initial_cash, flows)

    def _shifted_targets(self, aligned: dict[str, pd.DataFrame]) -> dict[str, pd.Series]:
        """Per-symbol targets on the one-bar shift: decide on t, act on t+1."""
        return {
            sym: self.strategy.target_positions(frame).shift(1).fillna(0).astype(int)
            for sym, frame in aligned.items()
        }


def _first_bar(common: pd.DatetimeIndex, start: pd.Timestamp | None) -> int:
    """The index of the first bar at or after ``start`` (0 without one)."""
    if start is None:
        return 0
    first = int(common.searchsorted(pd.Timestamp(start), side="left"))
    if first >= len(common):
        raise ValueError(f"no bars on or after {start} to backtest")
    return first
