"""Scoring functions that rank contestants from their BacktestResult.

Besides the whole-run metrics there are two *robustness* scorers that carve the
realized equity curve into contiguous folds. Contestants carry fixed parameters
(nothing is fit during a run), so each segment of the realized curve is a
genuine out-of-sample fold — the same idea as ``tradebot.walkforward``, applied
after the fact. One lucky stretch can dominate a whole-run Sharpe; it cannot
dominate the worst fold.
"""

from __future__ import annotations

from typing import Callable

from ..backtest import BacktestResult

Scorer = Callable[[BacktestResult], float]

#: Fold count used by the robustness scorers.
ROBUSTNESS_FOLDS = 4


def _calmar(result: BacktestResult) -> float:
    dd = abs(result.max_drawdown)
    return result.cagr / dd if dd > 1e-9 else 0.0


def fold_returns(result: BacktestResult, folds: int = ROBUSTNESS_FOLDS) -> list[float]:
    """Total return of each of ``folds`` contiguous equity-curve segments.

    Splits the per-bar *returns* (not the levels) so folds chain exactly:
    compounding the fold returns reproduces the whole-run total return.
    Degrades gracefully on short curves (never more folds than return bars).
    """
    rets = result.equity_curve.pct_change().dropna()
    n = len(rets)
    if n == 0:
        return [0.0]
    folds = max(1, min(folds, n))
    edges = [round(k * n / folds) for k in range(folds + 1)]
    out = []
    for lo, hi in zip(edges, edges[1:]):
        seg = rets.iloc[lo:hi]
        if not seg.empty:
            out.append(float((1.0 + seg).prod() - 1.0))
    return out or [0.0]


def _worst_fold(result: BacktestResult) -> float:
    return min(fold_returns(result))


def _consistency(result: BacktestResult) -> float:
    """Mean fold return minus fold-return dispersion (population std).

    Two contestants with the same average are separated by how evenly they
    earned it — a regime-dependence penalty.
    """
    rs = fold_returns(result)
    mean = sum(rs) / len(rs)
    std = (sum((r - mean) ** 2 for r in rs) / len(rs)) ** 0.5
    return mean - std


SCORERS: dict[str, Scorer] = {
    "sharpe": lambda r: r.sharpe,
    "total_return": lambda r: r.total_return,
    "cagr": lambda r: r.cagr,
    "calmar": _calmar,
    "worst_fold": _worst_fold,
    "consistency": _consistency,
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
