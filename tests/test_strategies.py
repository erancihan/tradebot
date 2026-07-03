import numpy as np
import pandas as pd
import pytest

from tradebot.data.synthetic import synthetic_ohlcv
from tradebot.strategies import (
    BollingerReversion,
    DonchianBreakout,
    MacdTrend,
    RsiReversion,
    SmaCrossover,
    build_strategy,
)


def _frame_from_close(close: pd.Series) -> pd.DataFrame:
    idx = pd.date_range("2023-01-02", periods=len(close), freq="1D", tz="UTC")
    close.index = idx
    return pd.DataFrame(
        {"open": close, "high": close, "low": close, "close": close,
         "volume": 1_000_000.0},
        index=idx,
    )


def test_sma_targets_are_in_valid_set():
    df = synthetic_ohlcv(periods=300, seed=1)
    target = SmaCrossover(10, 30).target_positions(df)
    assert set(np.unique(target)).issubset({0, 1})
    assert len(target) == len(df)


def test_sma_goes_long_on_uptrend():
    # Monotonic uptrend -> fast above slow -> long by the end.
    close = pd.Series(np.linspace(10, 100, 200))
    df = _frame_from_close(close)
    target = SmaCrossover(10, 30).target_positions(df)
    assert target.iloc[-1] == 1


def test_sma_rejects_bad_params():
    with pytest.raises(ValueError):
        SmaCrossover(fast=50, slow=20)


def test_sma_can_short_when_enabled():
    close = pd.Series(np.linspace(100, 10, 200))  # downtrend
    df = _frame_from_close(close)
    target = SmaCrossover(10, 30, allow_short=True).target_positions(df)
    assert target.iloc[-1] == -1


def test_rsi_enters_long_when_oversold_then_holds():
    # Sharp drop pushes RSI below 30 (enter long), then a recovery.
    close = pd.Series(
        list(np.linspace(100, 60, 40)) + list(np.linspace(60, 80, 40))
    )
    df = _frame_from_close(close)
    target = RsiReversion(period=14, oversold=30, exit_level=50).target_positions(df)
    assert set(np.unique(target)).issubset({0, 1})
    # It should have been long at some point during/after the oversold dip.
    assert (target == 1).any()


def test_donchian_goes_long_on_breakout_and_exits_on_breakdown():
    # Flat base, breakout rally, then a collapse through the exit channel.
    close = pd.Series(
        [100.0] * 40 + list(np.linspace(101, 130, 30)) + list(np.linspace(130, 90, 15))
    )
    df = _frame_from_close(close)
    target = DonchianBreakout(entry=20, exit=10).target_positions(df)
    assert set(np.unique(target)).issubset({0, 1})
    assert (target.iloc[:40] == 0).all()          # no position on the flat base
    assert target.iloc[55] == 1                   # long during the rally
    assert target.iloc[-1] == 0                   # stopped out by the collapse


def test_donchian_shorts_breakdown_when_enabled():
    close = pd.Series([100.0] * 40 + list(np.linspace(99, 60, 40)))
    df = _frame_from_close(close)
    target = DonchianBreakout(entry=20, exit=10, allow_short=True).target_positions(df)
    assert target.iloc[-1] == -1


def test_donchian_rejects_bad_channels():
    with pytest.raises(ValueError):
        DonchianBreakout(entry=10, exit=10)
    with pytest.raises(ValueError):
        DonchianBreakout(entry=10, exit=0)


def test_macd_trend_follows_the_trend_both_ways():
    up = _frame_from_close(pd.Series(np.linspace(10, 100, 200)))
    target = MacdTrend().target_positions(up)
    assert set(np.unique(target)).issubset({0, 1})
    assert target.iloc[-1] == 1

    down = _frame_from_close(pd.Series(np.linspace(100, 10, 200)))
    assert MacdTrend(allow_short=True).target_positions(down).iloc[-1] == -1
    assert MacdTrend().target_positions(down).iloc[-1] == 0   # long-only stays flat


def test_macd_trend_rejects_bad_params():
    with pytest.raises(ValueError):
        MacdTrend(fast=26, slow=12)
    with pytest.raises(ValueError):
        MacdTrend(signal=0)


def test_bollinger_buys_the_dip_and_exits_at_the_mean():
    # Stable regime, sharp dip below the band, then recovery through the mean.
    close = pd.Series(
        [100.0 + 0.1 * (i % 5) for i in range(60)]
        + list(np.linspace(99, 90, 8))            # dip: > 2 stdevs of the quiet regime
        + list(np.linspace(90, 104, 20))          # recovery through the middle band
    )
    df = _frame_from_close(close)
    target = BollingerReversion(window=20, num_std=2.0).target_positions(df)
    assert set(np.unique(target)).issubset({0, 1})
    assert (target == 1).any()                    # entered during the dip
    assert target.iloc[-1] == 0                   # exited once close >= middle band


def test_bollinger_shorts_the_spike_when_enabled():
    close = pd.Series(
        [100.0 + 0.1 * (i % 5) for i in range(60)]
        + list(np.linspace(101, 112, 8))          # spike above the upper band
    )
    df = _frame_from_close(close)
    target = BollingerReversion(window=20, allow_short=True).target_positions(df)
    assert target.iloc[-1] == -1
    # Long-only never shorts the same data.
    long_only = BollingerReversion(window=20).target_positions(df)
    assert set(np.unique(long_only)).issubset({0, 1})


def test_bollinger_rejects_bad_params():
    with pytest.raises(ValueError):
        BollingerReversion(window=1)
    with pytest.raises(ValueError):
        BollingerReversion(num_std=0)


def test_new_strategies_pass_a_walk_forward_smoke():
    """House rule: every new algo ships with a walk-forward pass (offline)."""
    from tradebot.backtest import Backtester
    from tradebot.risk import RiskConfig, RiskManager
    from tradebot.walkforward import walk_forward

    df = synthetic_ohlcv(periods=400, seed=9)
    for strategy in (DonchianBreakout(), MacdTrend(), BollingerReversion()):
        bt = Backtester(strategy, RiskManager(RiskConfig(max_position_pct=0.95)),
                        initial_cash=10_000, slippage_bps=1.0)
        wf = walk_forward(bt, df, folds=3)
        assert len(wf.folds) == 3
        assert all(np.isfinite(f.total_return) for f in wf.folds)


def test_registry_builds_known_strategies():
    s = build_strategy("sma_crossover", {"fast": 5, "slow": 20})
    assert isinstance(s, SmaCrossover)
    d = build_strategy("donchian_breakout", {"entry": 30, "exit": 15})
    assert isinstance(d, DonchianBreakout) and d.entry == 30
    assert isinstance(build_strategy("macd_trend"), MacdTrend)
    assert isinstance(build_strategy("bollinger_reversion"), BollingerReversion)
    with pytest.raises(KeyError):
        build_strategy("does_not_exist")
