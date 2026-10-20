"""What-if simulator: contributions, money gain, and the Backtester under it."""

import numpy as np
import pandas as pd
import pytest

from tradebot.backtest import Backtester
from tradebot.data.synthetic import synthetic_ohlcv
from tradebot.risk import RiskConfig, RiskManager
from tradebot.strategies import build_strategy
from tradebot.whatif import WhatIfPlan, monthly_cash_flows, run_whatif


def _flat(periods=120, price=100.0, start="2023-01-02"):
    index = pd.bdate_range(start, periods=periods, tz="UTC")
    return pd.DataFrame({"open": price, "high": price, "low": price, "close": price,
                         "volume": 1e6}, index=index)


def test_monthly_cash_flows_lands_on_first_bar_of_each_month():
    index = pd.bdate_range("2023-01-16", "2023-04-10", tz="UTC")
    flows = monthly_cash_flows(index, 200.0)
    assert sorted(ts.strftime("%Y-%m-%d") for ts in flows) == [
        "2023-02-01", "2023-03-01", "2023-04-03"]   # Apr 1 is a Saturday
    assert set(flows.values()) == {200.0}


def test_monthly_cash_flows_never_lands_on_the_first_bar():
    index = pd.bdate_range("2023-01-02", periods=30, tz="UTC")
    assert index[0] not in monthly_cash_flows(index, 100.0)
    assert monthly_cash_flows(index, 0.0) == {}


def test_contributions_raise_final_value_by_the_cash_put_in_when_prices_are_flat():
    frames = {"AAA": _flat(), "BBB": _flat(price=50.0)}
    plan = WhatIfPlan(symbols=["AAA", "BBB"], start="2023-01-02", end=None,
                      initial_cash=10_000, monthly_contribution=250)
    result = run_whatif(plan, frames, slippage_bps=0.0)
    months = len(monthly_cash_flows(result.plan.equity_curve.index, 1.0))
    assert months == 5
    assert result.contributions == pytest.approx(10_000 + 5 * 250)
    assert result.plan.final_equity == pytest.approx(result.contributions)
    # Flat prices earn nothing: the time-weighted metrics must not mistake the
    # saved cash for a return.
    assert result.plan.total_return == pytest.approx(0.0, abs=1e-12)
    assert result.plan.max_drawdown == pytest.approx(0.0, abs=1e-12)


def test_money_gain_excludes_contributions():
    df = synthetic_ohlcv(periods=300, seed=3, freq="B")
    plan = WhatIfPlan(symbols=["X"], start="2023-01-02", end=None,
                      initial_cash=5_000, monthly_contribution=100)
    result = run_whatif(plan, {"X": df})
    bt = result.plan
    assert bt.total_contributed == pytest.approx(5_000 + 100 * 13)   # Feb 2023 .. Feb 2024
    assert bt.money_gain == pytest.approx(bt.final_equity - bt.total_contributed)
    assert result.comparison["gain"] == pytest.approx(bt.money_gain, abs=0.01)
    summary = bt.summary()
    assert summary["total_contributed"] == round(bt.total_contributed, 2)


def test_contributions_are_invested_not_left_as_cash():
    df = synthetic_ohlcv(periods=300, seed=5, freq="B", drift=0.002, volatility=0.005)
    base = WhatIfPlan(symbols=["X"], start="2023-01-02", end=None, initial_cash=5_000)
    saver = WhatIfPlan(symbols=["X"], start="2023-01-02", end=None, initial_cash=5_000,
                       monthly_contribution=500)
    lump, monthly = run_whatif(base, {"X": df}), run_whatif(saver, {"X": df})
    # A rising market: invested contributions earn, so the extra value beats
    # the extra cash.
    extra_cash = monthly.contributions - lump.contributions
    assert monthly.plan.final_equity - lump.plan.final_equity > extra_cash


def _sma_bt():
    risk = RiskManager(RiskConfig(max_position_pct=0.95))
    return Backtester(build_strategy("sma_crossover", {"fast": 5, "slow": 20}), risk)


def test_backtester_without_cash_flows_is_unchanged():
    df = synthetic_ohlcv(periods=400, seed=42)
    default = _sma_bt().run(df)
    explicit = _sma_bt().run(df, cash_flows=None)
    pd.testing.assert_series_equal(default.equity_curve, explicit.equity_curve)
    assert default.summary() == explicit.summary()
    assert "money_gain" not in default.summary()
    assert default.total_contributed == default.initial_cash
    # An empty schedule is the same book: same curve, same metrics.
    empty = _sma_bt().run(df, cash_flows={})
    pd.testing.assert_series_equal(default.equity_curve, empty.equity_curve)
    assert empty.cagr == pytest.approx(default.cagr)
    assert empty.max_drawdown == pytest.approx(default.max_drawdown)
    assert np.allclose(empty.returns.to_numpy(), default.returns.to_numpy())


def test_a_cash_flow_off_the_timeline_is_refused():
    df = synthetic_ohlcv(periods=50, seed=1)
    with pytest.raises(ValueError, match="not a bar"):
        _sma_bt().run(df, cash_flows={pd.Timestamp("1999-01-01", tz="UTC"): 1.0})


def test_plan_rejects_nonsense():
    with pytest.raises(ValueError):
        WhatIfPlan(symbols=[], start="2023-01-02", end=None, initial_cash=1)
    with pytest.raises(ValueError):
        WhatIfPlan(symbols=["X"], start="2023-01-02", end=None, initial_cash=0)
    with pytest.raises(ValueError):
        WhatIfPlan(symbols=["X"], start="2023-01-02", end=None, initial_cash=1,
                   monthly_contribution=-1)


def test_run_whatif_with_a_strategy_plan_matches_backtester_directly():
    """Lockstep: the what-if wrapper adds contributions, nothing else."""
    from tradebot.allocation import InverseVolatility
    from tradebot.selection import MomentumSelector
    from tradebot.whatif import whatif_risk

    frames = {s: synthetic_ohlcv(periods=320, seed=20 + i, freq="B")
              for i, s in enumerate(["A", "B", "C", "D"])}
    plan = WhatIfPlan(symbols=list(frames), start="2023-01-02", end=None,
                      initial_cash=10_000, monthly_contribution=300,
                      strategy="sma_crossover", strategy_params={"fast": 5, "slow": 20},
                      allocation="inverse_vol", selector="momentum",
                      selector_params={"lookback": 60, "skip": 5, "top_k": 2})
    result = run_whatif(plan, frames)

    direct = Backtester(build_strategy("sma_crossover", {"fast": 5, "slow": 20}),
                        whatif_risk(), initial_cash=10_000,
                        allocator=InverseVolatility(),
                        selector=MomentumSelector(lookback=60, skip=5, top_k=2))
    flows = monthly_cash_flows(frames["A"].index, 300)
    expected = direct.run(frames, cash_flows=flows)
    pd.testing.assert_series_equal(result.plan.equity_curve, expected.equity_curve)
    assert result.plan.num_trades == expected.num_trades > 0


def test_benchmark_is_equal_weight_buy_and_hold_with_the_same_cash_flows():
    from tradebot.allocation import EqualWeight
    from tradebot.strategies.buy_and_hold import BuyAndHold
    from tradebot.whatif import whatif_risk

    frames = {s: synthetic_ohlcv(periods=260, seed=40 + i, freq="B")
              for i, s in enumerate(["A", "B", "C"])}
    plan = WhatIfPlan(symbols=list(frames), start="2023-01-02", end=None,
                      initial_cash=8_000, monthly_contribution=150,
                      strategy="sma_crossover", strategy_params={"fast": 5, "slow": 20})
    result = run_whatif(plan, frames)

    direct = Backtester(BuyAndHold(), whatif_risk(), initial_cash=8_000,
                        allocator=EqualWeight())
    expected = direct.run(frames, cash_flows=monthly_cash_flows(frames["A"].index, 150))
    pd.testing.assert_series_equal(result.benchmark.equity_curve, expected.equity_curve)
    assert result.benchmark.total_contributed == result.plan.total_contributed
    c = result.comparison
    assert c["benchmark_final"] == round(expected.final_equity, 2)
    assert c["vs_benchmark_pct"] == pytest.approx(
        result.plan.final_equity / expected.final_equity - 1, abs=1e-4)
    for key in ("final_value", "benchmark_final", "contributions", "gain",
                "benchmark_gain", "cagr", "max_drawdown", "vs_benchmark_pct"):
        assert key in c


def test_a_buy_and_hold_plan_ties_its_benchmark():
    frames = {s: synthetic_ohlcv(periods=200, seed=60 + i, freq="B") for i, s in enumerate("XY")}
    plan = WhatIfPlan(symbols=["X", "Y"], start="2023-01-02", end=None, initial_cash=1_000,
                      monthly_contribution=50)
    assert run_whatif(plan, frames).comparison["vs_benchmark_pct"] == 0.0


def _invested_book(returns: pd.Series, flows: pd.Series, initial: float) -> pd.Series:
    """A fully invested book: each bar's contribution arrives at the open and
    earns that bar's return alongside the capital already there."""
    equity, prev = [], initial
    for r, f in zip(returns, flows):
        prev = (prev + f) * (1.0 + r)
        equity.append(prev)
    return pd.Series(equity, index=returns.index)


def test_growth_index_does_not_depend_on_the_contribution_schedule():
    from tradebot.backtest.flows import growth_index

    closes = synthetic_ohlcv(periods=260, seed=7, freq="B", volatility=0.03)["close"]
    returns = closes.pct_change().fillna(0.0)
    none = pd.Series(0.0, index=returns.index)
    some = none.copy()
    some.iloc[::21] = 10_000.0
    some.iloc[0] = 0.0
    a = growth_index(_invested_book(returns, none, 100.0), none, 100.0)
    b = growth_index(_invested_book(returns, some, 100.0), some, 100.0)
    assert np.allclose(a.to_numpy(), b.to_numpy(), rtol=0, atol=1e-9)
    assert np.allclose(a.to_numpy(), (1.0 + returns).cumprod().to_numpy(), atol=1e-9)


def test_a_huge_contribution_cannot_push_returns_below_minus_100_percent():
    df = synthetic_ohlcv(periods=300, seed=8, freq="B", volatility=0.03)
    plan = WhatIfPlan(symbols=["X"], start="2023-01-02", end=None,
                      initial_cash=100, monthly_contribution=10_000)
    bt = run_whatif(plan, {"X": df}).plan
    assert bt.total_return >= -1.0
    assert -1.0 <= bt.max_drawdown <= 0.0


# --- warmup: a plan decides from bars before its start, and trades from it ----

def _warm_frames(seed=11):
    return {s: synthetic_ohlcv(periods=600, seed=seed + i, freq="B", drift=0.001)
            for i, s in enumerate("XY")}


def test_a_plan_is_invested_from_its_start_not_after_its_warmup():
    frames = _warm_frames()
    start = frames["X"].index[300]
    plan = WhatIfPlan(symbols=["X", "Y"], start=str(start.date()), end=None,
                      initial_cash=10_000, strategy="sma_crossover")
    strategy = build_strategy("sma_crossover")
    decided = {s: int(strategy.target_positions(df.loc[:start].iloc[:-1]).iloc[-1])
               for s, df in frames.items()}
    assert any(decided.values())      # the seed decides "in" on the bar before start
    result = run_whatif(plan, frames)
    curve, bench = result.plan.equity_curve, result.benchmark.equity_curve
    assert curve.index[0] == bench.index[0] == start          # one first date
    assert len(curve) == 300
    assert (curve.iloc[:3] != 10_000).any()                   # moves at once, no idle warmup


def test_a_buy_and_hold_plan_still_ties_its_benchmark_after_warmup():
    frames = _warm_frames(seed=21)
    plan = WhatIfPlan(symbols=["X", "Y"], start=str(frames["X"].index[300].date()),
                      end=None, initial_cash=1_000, monthly_contribution=50)
    result = run_whatif(plan, frames)
    assert result.comparison["vs_benchmark_pct"] == 0.0
    assert result.benchmark.equity_curve.iloc[0] != 1_000     # bought at the start's open


def test_the_backtester_start_drops_warmup_rows_from_the_result_only():
    frames = _warm_frames()
    start = frames["X"].index[300]
    bt = Backtester(build_strategy("buy_and_hold"), RiskManager(RiskConfig()))
    warm = bt.run(frames, start=start)
    cold = bt.run({s: df.loc[start:] for s, df in frames.items()})
    assert warm.equity_curve.index.equals(cold.equity_curve.index)
    # Warm, the decision formed on the bar before start fills at start's open;
    # cold, the first bar has no prior decision and sits in cash.
    assert warm.equity_curve.iloc[0] != bt.initial_cash == cold.equity_curve.iloc[0]
    with pytest.raises(ValueError, match="no bars"):
        bt.run(frames, start=frames["X"].index[-1] + pd.Timedelta(days=5))
