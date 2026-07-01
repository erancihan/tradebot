"""Event-driven backtester.

Runs the *same* Strategy and RiskManager objects the live engine uses, so a
backtest exercises the real decision/sizing code. To avoid look-ahead bias,
targets computed from bar ``t``'s close are executed at bar ``t+1``'s open
(targets are shifted by one bar), with optional slippage and commission.

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
    ) -> None:
        self.strategy = strategy
        self.risk = risk
        self.initial_cash = initial_cash
        self.commission = commission
        self.slippage_bps = slippage_bps

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

        # Pre-compute shifted targets per symbol: decide on t, act on t+1.
        targets: dict[str, pd.Series] = {}
        for sym, df in data.items():
            t = self.strategy.target_positions(df).reindex(common).shift(1).fillna(0)
            targets[sym] = t.astype(int)

        opens = {s: df["open"].reindex(common) for s, df in data.items()}
        closes = {s: df["close"].reindex(common) for s, df in data.items()}

        pf = Portfolio(cash=self.initial_cash)
        equity_points: list[float] = []
        slip = self.slippage_bps / 10_000.0

        for ts in common:
            close_prices = {s: float(closes[s].loc[ts]) for s in data}
            equity = pf.equity(close_prices)

            for sym in data:
                price = float(opens[sym].loc[ts])
                if not np.isfinite(price) or price <= 0:
                    continue
                desired = self.risk.target_qty(int(targets[sym].loc[ts]), equity, price)
                current = pf.position(sym).qty
                delta = desired - current
                if self.risk.config.allow_fractional:
                    if abs(delta) < 1e-9:
                        continue
                else:
                    delta = float(round(delta))
                    if delta == 0:
                        continue

                # Respect the gross-exposure cap when *increasing* exposure.
                increasing = (current == 0) or ((current > 0) == (delta > 0))
                if increasing:
                    other_gross = pf.gross_exposure(close_prices, exclude=sym)
                    delta = self.risk.clamp_to_exposure(delta, price, equity, other_gross)
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

        curve = pd.Series(equity_points, index=common, name="equity")
        return BacktestResult(
            equity_curve=curve,
            trades=pf.trades,
            initial_cash=self.initial_cash,
            periods_per_year=_infer_periods_per_year(common),
        )
