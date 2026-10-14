"""Walk-forward evaluation: does the pipeline work *across* regimes, or once?

A single backtest number can be one lucky stretch. Walk-forward splits the
history into ``folds`` contiguous out-of-sample segments and runs the *same*
configured pipeline (strategy + selector + allocator + overlays + risk)
independently on each: every fold starts fresh with the full warmup of history
it needs, and its metrics are measured only on the fold's own span. Consistent
folds are (weak) evidence of robustness; one great fold carrying an otherwise
flat set is a red flag for regime-dependence or luck.

This is *evaluation* discipline, not parameter fitting — tradebot's strategies
have no trained parameters, so there is no in-sample/out-of-sample leakage to
manage beyond the warmup prefix each fold is given. If you tune knobs by
re-running walk-forward until it looks good, you have reintroduced the
data-snooping this exists to expose: count your attempts and stay honest.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .backtest import BacktestResult, Backtester, _infer_periods_per_year


@dataclass(frozen=True)
class FoldMetrics:
    fold: int
    start: str
    end: str
    bars: int
    total_return: float
    sharpe: float
    max_drawdown: float


@dataclass
class WalkForwardResult:
    folds: list[FoldMetrics]

    @property
    def mean_return(self) -> float:
        return sum(f.total_return for f in self.folds) / len(self.folds)

    @property
    def worst_return(self) -> float:
        return min(f.total_return for f in self.folds)

    @property
    def positive_folds(self) -> int:
        return sum(1 for f in self.folds if f.total_return > 0)

    def table(self) -> str:
        lines = [
            f"{'fold':>4}  {'span':<23} {'bars':>5} {'return':>8} {'sharpe':>7} {'maxDD':>8}",
            "-" * 62,
        ]
        for f in self.folds:
            lines.append(
                f"{f.fold:>4}  {f.start[:10]} → {f.end[:10]}  {f.bars:>5} "
                f"{f.total_return:>7.2%} {f.sharpe:>7.2f} {f.max_drawdown:>7.2%}"
            )
        lines.append("-" * 62)
        lines.append(
            f"{'':>4}  {'mean / worst / positive':<23} {'':>5} "
            f"{self.mean_return:>7.2%} {'':>7} {self.worst_return:>7.2%}"
            f"   ({self.positive_folds}/{len(self.folds)} folds > 0)"
        )
        return "\n".join(lines)


def required_warmup(backtester: Backtester) -> int:
    """Bars of history the pipeline needs before its decisions mean anything."""
    needed = backtester.strategy.required_history
    for component in (backtester.selector, backtester.allocator, *backtester.overlays):
        if component is not None:
            needed = max(needed, component.required_history)
    return needed + 2   # one-bar shift + first fill


def walk_forward(
    backtester: Backtester,
    data: dict[str, pd.DataFrame] | pd.DataFrame,
    folds: int = 4,
    warmup: int | None = None,
    symbol: str = "ASSET",
) -> WalkForwardResult:
    """Evaluate the pipeline independently over ``folds`` contiguous segments.

    Each fold's backtest window includes the preceding ``warmup`` bars so
    selectors/allocators are warm from the fold's first bar, but metrics are
    computed only over the fold's own span. The first fold's warmup comes out
    of the data's head, so fold 1 starts at bar ``warmup``.
    """
    if isinstance(data, pd.DataFrame):
        data = {symbol: data}
    if folds < 2:
        raise ValueError(f"folds must be >= 2, got {folds}")
    if warmup is None:
        warmup = required_warmup(backtester)

    common = None
    for df in data.values():
        common = df.index if common is None else common.intersection(df.index)
    common = common.sort_values()

    usable = len(common) - warmup
    if usable < folds * 5:
        raise ValueError(
            f"Not enough history for {folds} folds: {len(common)} bars minus "
            f"{warmup} warmup leaves {max(usable, 0)} (need >= {folds * 5}). "
            "Fetch more history or reduce folds/lookbacks."
        )

    # Contiguous fold spans over the post-warmup range.
    edges = [warmup + round(k * usable / folds) for k in range(folds + 1)]

    results: list[FoldMetrics] = []
    for k in range(folds):
        lo, hi = edges[k], edges[k + 1]              # fold spans bars [lo, hi)
        window = common[lo - warmup: hi]             # + warmup prefix
        sliced = {s: df.reindex(window) for s, df in data.items()}
        res = backtester.run(sliced)

        span = hi - lo
        curve = res.equity_curve.iloc[-span:]
        fold_result = BacktestResult(
            equity_curve=curve,
            trades=[],
            initial_cash=float(curve.iloc[0]),
            periods_per_year=_infer_periods_per_year(curve.index),
        )
        results.append(FoldMetrics(
            fold=k + 1,
            start=str(curve.index[0]),
            end=str(curve.index[-1]),
            bars=span,
            total_return=fold_result.total_return,
            sharpe=fold_result.sharpe,
            max_drawdown=fold_result.max_drawdown,
        ))
    return WalkForwardResult(folds=results)
