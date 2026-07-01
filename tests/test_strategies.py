import numpy as np
import pandas as pd
import pytest

from tradebot.data.synthetic import synthetic_ohlcv
from tradebot.strategies import (
    STRATEGIES,
    BollingerReversion,
    DonchianBreakout,
    Macd,
    Momentum,
    RsiReversion,
    SmaCrossover,
    Supertrend,
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


def test_registry_builds_known_strategies():
    s = build_strategy("sma_crossover", {"fast": 5, "slow": 20})
    assert isinstance(s, SmaCrossover)
    with pytest.raises(KeyError):
        build_strategy("does_not_exist")


# --- Contract: every registered strategy obeys the {-1, 0, +1} regime ------------

@pytest.mark.parametrize("name", sorted(STRATEGIES))
def test_every_strategy_emits_valid_targets_and_alignment(name):
    df = synthetic_ohlcv(periods=400, seed=7)
    # Default params, but let short-capable ones exercise the short path too.
    for params in ({}, {"allow_short": True}):
        try:
            strat = build_strategy(name, params)
        except TypeError:
            continue  # strategy doesn't take allow_short; the {} pass covered it
        target = strat.target_positions(df)
        assert len(target) == len(df)
        assert target.index.equals(df.index)          # aligned to the bars
        assert set(np.unique(target)).issubset({-1, 0, 1})
        assert not target.isna().any()                # warm-up defaults to flat, not NaN


# --- MACD ------------------------------------------------------------------------

def test_macd_goes_long_on_uptrend():
    close = pd.Series(np.linspace(10, 100, 200))
    df = _frame_from_close(close)
    assert Macd(fast=5, slow=13, signal=4).target_positions(df).iloc[-1] == 1


def test_macd_can_short_on_downtrend():
    close = pd.Series(np.linspace(100, 10, 200))
    df = _frame_from_close(close)
    target = Macd(fast=5, slow=13, signal=4, allow_short=True).target_positions(df)
    assert target.iloc[-1] == -1


def test_macd_rejects_bad_params():
    with pytest.raises(ValueError):
        Macd(fast=26, slow=12)


# --- Bollinger reversion ---------------------------------------------------------

def test_bollinger_enters_long_on_lower_band_pierce_then_holds():
    # A sharp one-bar dip against a calm window pierces the lower band (enter
    # long); the snap back up through the mean exits. A smooth linear decline
    # never exceeds ~1.65 sigma, so an abrupt move is what triggers reversion.
    close = pd.Series([100.0] * 60)
    close.iloc[45] = 70.0
    df = _frame_from_close(close)
    target = BollingerReversion(window=20, num_std=2.0).target_positions(df)
    assert set(np.unique(target)).issubset({0, 1})
    assert (target == 1).any()


def test_bollinger_rejects_bad_params():
    with pytest.raises(ValueError):
        BollingerReversion(num_std=0)
    with pytest.raises(ValueError):
        BollingerReversion(window=1)


# --- Donchian breakout -----------------------------------------------------------

def test_donchian_goes_long_on_breakout():
    # Range then a decisive breakout to new highs -> long by the end.
    close = pd.Series(
        list(100 + np.sin(np.linspace(0, 6, 40)) * 2) + list(np.linspace(102, 140, 40))
    )
    df = _frame_from_close(close)
    target = DonchianBreakout(entry_window=20, exit_window=10).target_positions(df)
    assert set(np.unique(target)).issubset({0, 1})
    assert target.iloc[-1] == 1


def test_donchian_rejects_bad_params():
    with pytest.raises(ValueError):
        DonchianBreakout(entry_window=10, exit_window=20)  # exit must be <= entry


# --- Momentum --------------------------------------------------------------------

def test_momentum_long_on_positive_roc():
    close = pd.Series(np.linspace(50, 150, 200))
    df = _frame_from_close(close)
    target = Momentum(lookback=30, threshold=1.0).target_positions(df)
    assert target.iloc[-1] == 1


def test_momentum_trend_filter_blocks_counter_trend_long():
    # Strong recent bounce (positive ROC) but price still below a long SMA.
    close = pd.Series(list(np.linspace(200, 100, 160)) + list(np.linspace(100, 108, 20)))
    df = _frame_from_close(close)
    filtered = Momentum(lookback=10, threshold=0.0, trend_ma=100).target_positions(df)
    assert filtered.iloc[-1] == 0  # trend filter vetoes the counter-trend long


def test_momentum_rejects_bad_params():
    with pytest.raises(ValueError):
        Momentum(threshold=-1.0)


# --- Supertrend ------------------------------------------------------------------

def test_supertrend_long_on_uptrend_short_on_downtrend():
    up = _frame_from_close(pd.Series(np.linspace(10, 100, 200)))
    assert Supertrend(period=10, multiplier=3.0).target_positions(up).iloc[-1] == 1

    down = _frame_from_close(pd.Series(np.linspace(100, 10, 200)))
    long_only = Supertrend(period=10, multiplier=3.0).target_positions(down)
    assert long_only.iloc[-1] == 0                      # down-trend -> flat when long-only
    shorted = Supertrend(period=10, multiplier=3.0, allow_short=True).target_positions(down)
    assert shorted.iloc[-1] == -1


def test_supertrend_rejects_bad_params():
    with pytest.raises(ValueError):
        Supertrend(multiplier=0)
