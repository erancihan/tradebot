import numpy as np
import pandas as pd
import pytest

from tradebot.data.synthetic import synthetic_ohlcv
from tradebot.strategies import RsiReversion, SmaCrossover, build_strategy


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


def test_registry_builds_known_strategies():
    s = build_strategy("sma_crossover", {"fast": 5, "slow": 20})
    assert isinstance(s, SmaCrossover)
    with pytest.raises(KeyError):
        build_strategy("does_not_exist")
