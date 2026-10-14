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
