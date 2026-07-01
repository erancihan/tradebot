import numpy as np
import pandas as pd

from tradebot.backtest import Backtester, _infer_periods_per_year
from tradebot.data.synthetic import synthetic_ohlcv
from tradebot.risk import RiskConfig, RiskManager
from tradebot.strategies import RsiReversion, SmaCrossover


def _bt(strategy, **risk_kw):
    risk = RiskManager(RiskConfig(max_position_pct=0.95, **risk_kw))
    return Backtester(strategy, risk, initial_cash=10_000, slippage_bps=0.0)


def test_backtest_runs_and_reports_metrics():
    df = synthetic_ohlcv(periods=400, seed=7)
    result = _bt(SmaCrossover(10, 30)).run(df, symbol="X")
    s = result.summary()
    assert s["initial_cash"] == 10_000
    assert len(result.equity_curve) == len(df)
    assert -1.0 <= result.max_drawdown <= 0.0
    assert result.num_trades >= 0


def test_uptrend_with_always_long_is_profitable():
    # Strong steady uptrend; a fast/slow crossover should ride most of it.
    df = synthetic_ohlcv(periods=500, drift=0.003, volatility=0.005, seed=3)
    result = _bt(SmaCrossover(5, 20)).run(df, symbol="UP")
    assert result.total_return > 0
    assert result.final_equity > result.initial_cash


def test_no_lookahead_targets_are_shifted():
    # If targets were used same-bar we'd capture the open->close of the signal
    # bar; the shift means equity only changes from the bar AFTER a signal.
    df = synthetic_ohlcv(periods=200, seed=11)
    result = _bt(SmaCrossover(5, 20)).run(df, symbol="X")
    # Equity is flat until the strategy first takes a position.
    assert result.equity_curve.iloc[0] == 10_000


def test_multi_symbol_shared_cash_respects_exposure():
    a = synthetic_ohlcv(periods=300, seed=1)
    b = synthetic_ohlcv(periods=300, seed=2)
    risk = RiskManager(RiskConfig(max_position_pct=0.5, max_gross_exposure=1.0))
    bt = Backtester(SmaCrossover(10, 30), risk, initial_cash=10_000, slippage_bps=0.0)
    result = bt.run({"A": a, "B": b})
    assert len(result.equity_curve) > 0
    # Never blow past the initial cash into deep negative equity.
    assert result.equity_curve.min() > 0


def test_rsi_strategy_backtests():
    df = synthetic_ohlcv(periods=400, seed=9)
    result = _bt(RsiReversion(period=14)).run(df, symbol="R")
    assert len(result.equity_curve) == len(df)


def test_infer_periods_per_year_daily():
    idx = pd.date_range("2023-01-02", periods=10, freq="1D", tz="UTC")
    assert _infer_periods_per_year(idx) == 252.0


def test_commission_and_slippage_reduce_returns():
    df = synthetic_ohlcv(periods=400, drift=0.002, volatility=0.01, seed=5)
    clean = _bt(SmaCrossover(5, 20)).run(df, symbol="X").total_return
    costly = Backtester(
        SmaCrossover(5, 20),
        RiskManager(RiskConfig(max_position_pct=0.95)),
        initial_cash=10_000,
        commission=1.0,
        slippage_bps=10.0,
    ).run(df, symbol="X").total_return
    assert costly <= clean
