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
    #: Per-bar contributions (zeros between them), or None for a closed book.
    #: When set, the time-weighted metrics strip them out (see ``flows.py``);
    #: when None every metric is computed exactly as it always was.
    cash_flows: pd.Series | None = None

    @property
    def final_equity(self) -> float:
        return float(self.equity_curve.iloc[-1])

    @property
    def total_contributed(self) -> float:
        """Every unit of cash put in: the starting cash plus all contributions."""
        extra = 0.0 if self.cash_flows is None else float(self.cash_flows.sum())
        return self.initial_cash + extra

    @property
    def money_gain(self) -> float:
        """Final value minus all cash put in: what the plan actually made."""
        return self.final_equity - self.total_contributed

    def _growth(self) -> pd.Series | None:
        if self.cash_flows is None:
            return None
        from .flows import growth_index

        return growth_index(self.equity_curve, self.cash_flows, self.initial_cash)

    @property
    def total_return(self) -> float:
        growth = self._growth()
        if growth is not None:
            return float(growth.iloc[-1]) - 1.0
        return self.final_equity / self.initial_cash - 1.0

    def _anchored(self) -> tuple[pd.Series, float]:
        """(curve, its value before bar one): equity from ``initial_cash``, or
        growth from 1.0. Since ``run(start=)`` the book can be invested on bar
        one, so its move is a return like any other, in every metric."""
        growth = self._growth()
        if growth is not None:
            return growth, 1.0
        return self.equity_curve, float(self.initial_cash)

    @property
    def returns(self) -> pd.Series:
        curve, base = self._anchored()
        r = curve.pct_change()
        if len(r) and base > 0:
            r.iloc[0] = float(curve.iloc[0]) / base - 1.0
        return r.dropna()

    @property
    def cagr(self) -> float:
        n = len(self.equity_curve)
        growth = self._growth()
        ending = self.final_equity / self.initial_cash if growth is None else float(growth.iloc[-1])
        if n < 2 or ending <= 0:
            return 0.0
        years = n / self.periods_per_year
        if years <= 0:
            return 0.0
        return ending ** (1.0 / years) - 1.0

    @property
    def sharpe(self) -> float:
        r = self.returns
        if r.empty or r.std(ddof=0) == 0:
            return 0.0
        return float(r.mean() / r.std(ddof=0) * math.sqrt(self.periods_per_year))

    @property
    def max_drawdown(self) -> float:
        curve, base = self._anchored()
        peak = curve.cummax().clip(lower=base) if base > 0 else curve.cummax()
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
        out = {
            "initial_cash": self.initial_cash,
            "final_equity": round(self.final_equity, 2),
            "total_return": round(self.total_return, 4),
            "cagr": round(self.cagr, 4),
            "sharpe": round(self.sharpe, 3),
            "max_drawdown": round(self.max_drawdown, 4),
            "num_trades": self.num_trades,
            "win_rate": round(self.win_rate, 4),
        }
        if self.cash_flows is not None:
            out["total_contributed"] = round(self.total_contributed, 2)
            out["money_gain"] = round(self.money_gain, 2)
        return out


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
