"""Scoring functions that rank contestants from their BacktestResult."""

from __future__ import annotations

from typing import Callable

from ..backtest import BacktestResult

Scorer = Callable[[BacktestResult], float]


def _calmar(result: BacktestResult) -> float:
    dd = abs(result.max_drawdown)
    return result.cagr / dd if dd > 1e-9 else 0.0


SCORERS: dict[str, Scorer] = {
    "sharpe": lambda r: r.sharpe,
    "total_return": lambda r: r.total_return,
    "cagr": lambda r: r.cagr,
    "calmar": _calmar,
}


def available() -> list[str]:
    return list(SCORERS)


def get_scorer(metric: str) -> Scorer:
    try:
        return SCORERS[metric]
    except KeyError:
        raise ValueError(
            f"Unknown score metric {metric!r}. Available: {', '.join(available())}"
        ) from None
