"""Compare strategies: every rule on one plan, ranked, with the benchmark run once."""

import pandas as pd
import pytest

from tradebot.data.synthetic import synthetic_ohlcv
from tradebot.strategies import STRATEGIES, Strategy
from tradebot.whatif import WhatIfPlan, compare_strategies, needs_configuration, run_whatif

META = {"follow_leader", "ensemble_vote"}


def _frames(symbols=("AAA", "BBB", "CCC"), periods=300):
    return {s: synthetic_ohlcv(periods=periods, seed=7 + i, freq="B", start="2022-01-03")
            for i, s in enumerate(symbols)}


def _plan(**over):
    base = dict(symbols=["AAA", "BBB", "CCC"], start="2022-01-03", end=None,
                initial_cash=10_000, monthly_contribution=200)
    return WhatIfPlan(**{**base, **over})


class _Broken(Strategy):
    name = "broken"

    def target_positions(self, bars: pd.DataFrame) -> pd.Series:
        raise RuntimeError("this rule always fails")


def test_every_runnable_strategy_gets_a_ranked_row_and_meta_strategies_are_skipped():
    out = compare_strategies(_plan(), _frames())
    runnable = set(STRATEGIES) - META
    assert set(out.results) == runnable
    assert {s["name"] for s in out.skipped} == META
    assert all("roster" in s["reason"] for s in out.skipped)
    assert out.errors == []
    values = [r["final_value"] for r in out.rows()]
    assert values == sorted(values, reverse=True)
    assert set(out.rows()[0]) == {"name", "final_value", "gain", "cagr", "max_drawdown",
                                  "vs_benchmark_pct"}


def test_the_benchmark_row_is_marked_and_buy_and_hold_ties_it():
    out = compare_strategies(_plan(), _frames(), ["buy_and_hold"])
    bench = out.benchmark_row()
    assert bench["benchmark"] is True and bench["vs_benchmark_pct"] == 0.0
    row = out.row("buy_and_hold")
    assert row["final_value"] == pytest.approx(bench["final_value"])
    assert row["vs_benchmark_pct"] == 0.0


def test_a_strategy_that_raises_becomes_an_error_and_the_rest_still_run(monkeypatch):
    monkeypatch.setitem(STRATEGIES, "broken", _Broken)
    out = compare_strategies(_plan(), _frames(), ["broken", "buy_and_hold", "sma_crossover"])
    assert out.errors == [{"name": "broken", "error": "RuntimeError: this rule always fails"}]
    assert set(out.results) == {"buy_and_hold", "sma_crossover"}


def test_each_row_matches_a_single_what_if_run_with_default_params():
    frames = _frames()
    out = compare_strategies(_plan(), frames, ["sma_crossover"])
    single = run_whatif(_plan(strategy="sma_crossover"), frames)
    assert out.row("sma_crossover")["final_value"] == single.comparison["final_value"]
    assert out.benchmark.final_equity == single.benchmark.final_equity


def test_the_plan_strategy_params_are_replaced_by_each_rules_defaults():
    frames = _frames()
    tuned = _plan(strategy="sma_crossover", strategy_params={"fast": 5, "slow": 12})
    out = compare_strategies(tuned, frames, ["sma_crossover"])
    default = run_whatif(_plan(strategy="sma_crossover"), frames)
    assert out.row("sma_crossover")["final_value"] == default.comparison["final_value"]


def test_the_plan_selector_and_allocator_stay_on_every_rule():
    frames = _frames()
    plan = _plan(selector="momentum", selector_params={"top_k": 1, "lookback": 40, "skip": 5})
    out = compare_strategies(plan, frames, ["buy_and_hold"])
    single = run_whatif(plan, frames)
    assert out.row("buy_and_hold")["final_value"] == single.comparison["final_value"]


def test_strategies_left_when_the_time_budget_runs_out_are_skipped():
    ticks = iter([0.0, 0.0, 5.0, 5.0])
    out = compare_strategies(_plan(), _frames(), ["buy_and_hold", "sma_crossover"],
                             budget_s=1.0, clock=lambda: next(ticks))
    assert set(out.results) == {"buy_and_hold"}
    assert out.skipped == [{"name": "sma_crossover", "reason": "time budget of 1s used up"}]


def test_unknown_names_and_required_params_are_skipped_with_a_reason():
    class _NeedsArg(Strategy):
        def __init__(self, level: int) -> None:
            self.level = level

        def target_positions(self, bars):
            return pd.Series(1, index=bars.index)

    assert "level" in needs_configuration(_NeedsArg)
    assert needs_configuration(STRATEGIES["buy_and_hold"]) is None
    out = compare_strategies(_plan(), _frames(), ["nope"])
    assert out.skipped[0]["reason"].startswith("unknown strategy")


def test_a_tuned_plan_gets_its_own_row_and_only_that_row_is_the_plan():
    """The default-params row is not the user's plan; with strategy_params the
    plan runs once more as given, named "(your settings)" and flagged."""
    frames = _frames()
    tuned = _plan(strategy="sma_crossover", strategy_params={"fast": 5, "slow": 12})
    out = compare_strategies(tuned, frames, ["sma_crossover", "buy_and_hold"])
    mine = "sma_crossover (your settings)"
    assert set(out.results) == {"sma_crossover", mine, "buy_and_hold"}
    assert out.row(mine)["plan"] is True
    assert "plan" not in out.row("sma_crossover") and "plan" not in out.row("buy_and_hold")
    single = run_whatif(tuned, frames)
    assert out.row(mine)["final_value"] == single.comparison["final_value"]
    assert out.row(mine)["final_value"] != out.row("sma_crossover")["final_value"]


def test_an_untuned_plan_flags_its_plain_row():
    out = compare_strategies(_plan(strategy="sma_crossover"), _frames(),
                             ["sma_crossover", "buy_and_hold"])
    assert set(out.results) == {"sma_crossover", "buy_and_hold"}
    assert out.row("sma_crossover")["plan"] is True
    assert "plan" not in out.row("buy_and_hold")
