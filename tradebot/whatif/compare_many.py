"""Every decision rule on one plan: which would have done best?

The plan's symbols, dates, cash, allocator and selector stay fixed; only the
strategy changes, each with its default parameters. The window, the cash
flows and the benchmark are computed once, so every row answers the same
question over the same bars with the same money.

The plan's own row is flagged ``plan``. A plan with ``strategy_params`` is not
its strategy's default row, so it runs once more as given, named
``"<strategy> (your settings)"``; the default row keeps the plain name.
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
from .run import plan_window, run_plan, warmup_bars

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
    plan_name: str | None = None         # the row that is the user's plan, if it ran

    def row(self, name: str) -> dict:
        numbers = comparison(self.results[name], self.benchmark)
        flag = {"plan": True} if name == self.plan_name else {}
        return {"name": name, **flag, **{k: numbers[k] for k in ROW_KEYS}}

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
    window, flows = plan_window(plan, frames, _warmup(plan, names))
    costs = {"commission": commission, "slippage_bps": slippage_bps}
    benchmark = run_plan(benchmark_plan(plan), window, flows, **costs)
    deadline = None if budget_s is None else clock() + budget_s
    results, errors, skipped = {}, [], []
    plan_name = plan.strategy
    if plan.strategy_params:               # the plan as given, before any budget runs out
        plan_name = f"{plan.strategy} (your settings)"
        try:
            results[plan_name] = run_plan(plan, window, flows, **costs)
        except Exception as exc:  # noqa: BLE001
            errors.append({"name": plan_name, "error": f"{type(exc).__name__}: {exc}"})
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
            results[name] = run_plan(rule, window, flows, **costs)
        except Exception as exc:  # noqa: BLE001 - one bad rule never sinks the rest
            errors.append({"name": name, "error": f"{type(exc).__name__}: {exc}"})
    ranked = dict(sorted(results.items(), key=lambda kv: -kv[1].final_equity))
    return StrategyComparison(benchmark=benchmark, results=ranked, errors=errors,
                              skipped=skipped,
                              plan_name=plan_name if plan_name in ranked else None)


def _warmup(plan: WhatIfPlan, names: list[str]) -> int:
    """The longest warmup any compared rule needs: one window for every row,
    each with enough history to decide on the start (a rule that cannot be
    built is ranked or skipped later, not here)."""
    from ..strategies import STRATEGIES

    need = [warmup_bars(plan)]
    for name in names:
        if name in STRATEGIES and needs_configuration(STRATEGIES[name]) is None:
            try:
                need.append(warmup_bars(replace(plan, strategy=name, strategy_params={})))
            except Exception:  # noqa: BLE001 - its own run reports the error
                continue
    return max(need)
