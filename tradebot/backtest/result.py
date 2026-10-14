"""Backtest result container and its performance metrics.

Shared by the vectorised :class:`~tradebot.backtest.Backtester` and the arena's
stepped ``simulate``, so every metric means the same thing in both loops.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

from ..models import Trade


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
