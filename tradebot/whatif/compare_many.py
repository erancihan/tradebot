"""Every decision rule on one plan: which would have done best?

The plan's symbols, dates, cash, allocator and selector stay fixed; only the
strategy changes, each with its default parameters. The window, the cash
flows and the benchmark are computed once, so every row answers the same
question over the same bars with the same money.
"""

from __future__ import annotations

import inspect
import time
from collections.abc import Callable
from dataclasses import dataclass, replace

import pandas as pd

from ..backtest import BacktestResult
from .compare import benchmark_plan, comparison
from .plan import WhatIfPlan
from .run import plan_backtester, plan_window

#: The numbers a ranked row carries, taken from :func:`comparison`.
ROW_KEYS = ("final_value", "gain", "cagr", "max_drawdown", "vs_benchmark_pct")
_SCALARS = (bool, int, float, str)


def needs_configuration(cls) -> str | None:
    """Why a strategy cannot run on defaults alone, or ``None`` when it can.

    A required parameter has no default, and a non-scalar default (a meta
    strategy's ``strategies=None`` roster) is a config-file choice the form
    cannot express. Meta strategies are also the expensive ones, so leaving
    them out keeps a comparison fast. ``*args``/``**kwargs`` are fine.
    """
    for name, p in inspect.signature(cls.__init__).parameters.items():
        if name == "self" or p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        if p.default is inspect.Parameter.empty:
            return f"needs {name!r}: set it in the config file"
        if not isinstance(p.default, _SCALARS):
            return f"needs a configured {name!r} (a roster or derived value)"
    return None


@dataclass(frozen=True)
class StrategyComparison:
    benchmark: BacktestResult
    results: dict[str, BacktestResult]   # best final value first
    errors: list[dict]                   # {name, error}: raised, the rest still ran
    skipped: list[dict]                  # {name, reason}: never started

    def row(self, name: str) -> dict:
        numbers = comparison(self.results[name], self.benchmark)
        return {"name": name, **{k: numbers[k] for k in ROW_KEYS}}

    def rows(self) -> list[dict]:
        return [self.row(name) for name in self.results]

    def benchmark_row(self) -> dict:
        numbers = comparison(self.benchmark, self.benchmark)
        return {"name": "benchmark", "benchmark": True,
                **{k: numbers[k] for k in ROW_KEYS}}


def compare_strategies(plan: WhatIfPlan, frames: dict[str, pd.DataFrame],
                       names: list[str] | None = None, *, budget_s: float | None = None,
                       clock: Callable[[], float] = time.monotonic,
                       commission: float = 0.0,
                       slippage_bps: float = 1.0) -> StrategyComparison:
    """Run ``plan`` once per strategy in ``names`` (default: the registry).

    One failing strategy becomes an ``errors`` entry and the rest still run.
    Strategies not started before ``budget_s`` elapses are ``skipped``, so a
    comparison always returns what it has instead of running unbounded.
    """
    from ..strategies import STRATEGIES

    names = sorted(STRATEGIES) if names is None else list(names)
    window, flows = plan_window(plan, frames)
    costs = {"commission": commission, "slippage_bps": slippage_bps}
    benchmark = plan_backtester(benchmark_plan(plan), **costs).run(window, cash_flows=flows)
    deadline = None if budget_s is None else clock() + budget_s
    results, errors, skipped = {}, [], []
    for name in names:
        reason = (f"unknown strategy {name!r}" if name not in STRATEGIES
                  else needs_configuration(STRATEGIES[name]))
        if reason is None and deadline is not None and clock() >= deadline:
            reason = f"time budget of {budget_s:g}s used up"
        if reason is not None:
            skipped.append({"name": name, "reason": reason})
            continue
        try:
            rule = replace(plan, strategy=name, strategy_params={})
            results[name] = plan_backtester(rule, **costs).run(window, cash_flows=flows)
        except Exception as exc:  # noqa: BLE001 - one bad rule never sinks the rest
            errors.append({"name": name, "error": f"{type(exc).__name__}: {exc}"})
    ranked = dict(sorted(results.items(), key=lambda kv: -kv[1].final_equity))
    return StrategyComparison(benchmark=benchmark, results=ranked,
                              errors=errors, skipped=skipped)
