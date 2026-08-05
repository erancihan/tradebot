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

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .models import Trade
from .portfolio import Portfolio
from .risk import RiskManager
from .strategies.base import Strategy


def _sizing_marks(
    symbols,
    bar_opens: dict[str, float],
    prev_closes: dict[str, float],
    bar_closes: dict[str, float],
) -> dict[str, float]:
    """Prices to mark the book at when sizing a fill on this bar.

    Shared by :class:`Backtester` and ``arena.simulation.simulate`` so the two
    loops cannot drift apart — the lockstep invariant is structural here rather
    than merely asserted by a test.

    Order of preference per symbol: this bar's **open** (the price we are about
    to fill at, and already printed), then the **previous** bar's close, then
    this bar's close. That last fallback can only be reached on the first bar
    for a symbol with no usable open, when the book is still flat and the mark
    therefore cannot affect any quantity.

    Marking at this bar's close instead — which is what this loop used to do —
    sizes every fill with the return of the bar it fills on. The bias is not
    noise: it de-risks into down bars and levers into up bars, it scales with
    exposure and turnover so it does not cancel between a candidate and its
    benchmark, and it inflates results, so the failure mode is a false PASS.
    """
    marks = {}
    for s in symbols:
        price = bar_opens.get(s)
        if price is None:
            price = prev_closes.get(s, bar_closes[s])
        marks[s] = price
    return marks


def _prepare_components(aligned: dict, *components) -> None:
    """Give any component that wants it one look at the whole aligned frame set.

    Duck-typed, opt-in, and a no-op for everything that ships today. It exists
    for components whose per-bar answer is cheap only if a full-frame pass runs
    first — the consortium being the motivating case, where recomputing the
    member panel on every growing window would be quadratic.

    This is the same discipline selectors already get implicitly: `membership()`
    is called once over the full frame and then `.shift(1)`-ed, which is sound
    because the component is prefix-stable. **A component that uses this hook
    owes the same guarantee** — precompute freely, but never let bar `t`'s
    answer depend on a bar after `t`. Both execution loops call this at the same
    point, right after alignment, so the two cannot drift.

    Deduplicated by identity: one object may legitimately fill two roles at once
    (the consortium is its own signal *and* its own weighting, so it arrives as
    both the policy and the allocator). Preparing it twice would silently double
    the cost of the most expensive thing in the system — which is exactly how it
    first blew its time budget.
    """
    seen: set[int] = set()
    for component in components:
        if component is None or id(component) in seen:
            continue
        seen.add(id(component))
        prepare = getattr(component, "prepare", None)
        if callable(prepare):
            prepare(aligned)


@dataclass
class BacktestResult:
    equity_curve: pd.Series
    trades: list[Trade]
    initial_cash: float
    periods_per_year: float = 252.0

    @property
    def final_equity(self) -> float:
        return float(self.equity_curve.iloc[-1])

    @property
    def total_return(self) -> float:
        return self.final_equity / self.initial_cash - 1.0

    @property
    def returns(self) -> pd.Series:
        return self.equity_curve.pct_change().dropna()

    @property
    def cagr(self) -> float:
        n = len(self.equity_curve)
        if n < 2 or self.final_equity <= 0:
            return 0.0
        years = n / self.periods_per_year
        if years <= 0:
            return 0.0
        return (self.final_equity / self.initial_cash) ** (1.0 / years) - 1.0

    @property
    def sharpe(self) -> float:
        r = self.returns
        if r.empty or r.std(ddof=0) == 0:
            return 0.0
        return float(r.mean() / r.std(ddof=0) * math.sqrt(self.periods_per_year))

    @property
    def max_drawdown(self) -> float:
        curve = self.equity_curve
        peak = curve.cummax()
        dd = (curve - peak) / peak
        return float(dd.min())

    @property
    def num_trades(self) -> int:
        return len(self.trades)

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        wins = sum(1 for t in self.trades if t.is_win)
        return wins / len(self.trades)

    def summary(self) -> dict[str, float]:
        return {
            "initial_cash": self.initial_cash,
            "final_equity": round(self.final_equity, 2),
            "total_return": round(self.total_return, 4),
            "cagr": round(self.cagr, 4),
            "sharpe": round(self.sharpe, 3),
            "max_drawdown": round(self.max_drawdown, 4),
            "num_trades": self.num_trades,
            "win_rate": round(self.win_rate, 4),
        }


def _infer_periods_per_year(index: pd.DatetimeIndex) -> float:
    if len(index) < 3:
        return 252.0
    median_delta = pd.Series(index).diff().median()
    if pd.isna(median_delta) or median_delta == pd.Timedelta(0):
        return 252.0
    seconds = median_delta.total_seconds()
    if seconds >= 23 * 3600:          # daily-ish bars -> trading days
        return 252.0
    # Intraday: ~6.5 trading hours/day, 252 days/year.
    bars_per_day = (6.5 * 3600) / seconds
    return bars_per_day * 252.0


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

    def run(self, data: dict[str, pd.DataFrame] | pd.DataFrame, symbol: str = "ASSET") -> BacktestResult:
        if isinstance(data, pd.DataFrame):
            data = {symbol: data}
        if not data:
            raise ValueError("No data provided to backtest")

        # Align all symbols on a common timeline (intersection of indices).
        common = None
        for df in data.values():
            idx = df.index
            common = idx if common is None else common.intersection(idx)
        common = common.sort_values()
        if len(common) < 2:
            raise ValueError("Not enough overlapping bars to backtest")

        # Align first, then decide: the strategy, the selector and the allocator
        # must all see one timeline. Computing targets on each symbol's own raw
        # frame and reindexing afterwards diverges from the arena's stepped
        # loop (which only ever sees the intersection) whenever the symbols have
        # ragged indexes — which real bars do, and every lockstep fixture does
        # not.
        aligned = {s: df.reindex(common) for s, df in data.items()}
        _prepare_components(aligned, self.strategy, self.allocator, self.selector,
                            *self.overlays)

        # Pre-compute shifted targets per symbol: decide on t, act on t+1.
        targets: dict[str, pd.Series] = {}
        for sym in data:
            t = self.strategy.target_positions(aligned[sym]).shift(1).fillna(0)
            targets[sym] = t.astype(int)
        opens = {s: aligned[s]["open"] for s in data}
        closes = {s: aligned[s]["close"] for s in data}

        # Cross-sectional membership gates the targets, on the same one-bar
        # shift: selected using bars <= t, gating the fill at t+1.
        member = None
        if self.selector is not None:
            member = self.selector.membership(aligned).shift(1).fillna(False)

        pf = Portfolio(cash=self.initial_cash)
        equity_points: list[float] = []
        slip = self.slippage_bps / 10_000.0

        prev_closes: dict[str, float] = {}

        for i, ts in enumerate(common):
            close_prices = {s: float(closes[s].loc[ts]) for s in data}

            # Gather this bar's fillable symbols, then size the book jointly so
            # the result never depends on symbol iteration order.
            bar_targets: dict[str, int] = {}
            bar_prices: dict[str, float] = {}
            for sym in data:
                price = float(opens[sym].loc[ts])
                if not np.isfinite(price) or price <= 0:
                    continue
                target = int(targets[sym].loc[ts])
                if member is not None and not bool(member[sym].loc[ts]):
                    target = 0
                bar_targets[sym] = target
                bar_prices[sym] = price

            # Sizing marks the book at prices that have already printed when we
            # fill: this bar's open, falling back to the previous close for a
            # symbol whose open is unusable. Marking at THIS bar's close would
            # size every fill with the return of the bar it fills on — the
            # look-ahead this loop exists to avoid. The close is still the right
            # mark for the reported equity point at the end of the bar.
            sizing_prices = _sizing_marks(data, bar_prices, prev_closes, close_prices)
            equity = pf.equity(sizing_prices)

            weights = None
            if self.allocator is not None:
                # Weights obey the same one-bar shift as targets: decided from
                # bars strictly before the fill bar.
                history = {s: aligned[s].iloc[:i] for s in bar_targets}
                weights = self.allocator.weights(bar_targets, history)
                for overlay in self.overlays:
                    weights = overlay.transform(weights, bar_targets, history)
            desired = self.risk.allocate(bar_targets, equity, bar_prices, weights)

            for sym, want in desired.items():
                price = bar_prices[sym]
                delta = self.risk.material_delta(want, pf.position(sym).qty, price, equity)
                if self.risk.config.allow_fractional:
                    if abs(delta) < 1e-9:
                        continue
                else:
                    delta = float(round(delta))
                    if delta == 0:
                        continue
                fill_price = price * (1 + slip) if delta > 0 else price * (1 - slip)
                pf.execute(sym, delta, fill_price, commission=self.commission)

            equity_points.append(pf.equity(close_prices))
            prev_closes = close_prices

        curve = pd.Series(equity_points, index=common, name="equity")
        return BacktestResult(
            equity_curve=curve,
            trades=pf.trades,
            initial_cash=self.initial_cash,
            periods_per_year=_infer_periods_per_year(common),
        )
