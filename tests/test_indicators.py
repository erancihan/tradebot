import numpy as np
import pandas as pd
import pytest

from tradebot import indicators


def test_sma_matches_manual_mean():
    s = pd.Series([1, 2, 3, 4, 5], dtype=float)
    out = indicators.sma(s, 3)
    assert np.isnan(out.iloc[0]) and np.isnan(out.iloc[1])
    assert out.iloc[2] == 2.0  # mean(1,2,3)
    assert out.iloc[4] == 4.0  # mean(3,4,5)


def test_ema_no_lookahead_and_warmup():
    s = pd.Series(range(10), dtype=float)
    out = indicators.ema(s, 3)
    # First (window-1) values are NaN due to min_periods.
    assert out.iloc[:2].isna().all()
    assert not out.iloc[2:].isna().any()


def test_rsi_bounds_and_trend():
    # Strictly rising series -> RSI should saturate near 100.
    up = pd.Series(np.linspace(1, 100, 100))
    r = indicators.rsi(up, 14).dropna()
    assert (r >= 0).all() and (r <= 100).all()
    assert r.iloc[-1] > 99

    # Strictly falling series -> RSI near 0.
    down = pd.Series(np.linspace(100, 1, 100))
    rd = indicators.rsi(down, 14).dropna()
    assert rd.iloc[-1] < 1


def test_rsi_flat_series_is_neutral():
    flat = pd.Series([50.0] * 50)
    r = indicators.rsi(flat, 14).dropna()
    assert np.allclose(r, 50.0)


def test_crossover_detects_single_event():
    fast = pd.Series([1, 1, 3, 3], dtype=float)
    slow = pd.Series([2, 2, 2, 2], dtype=float)
    cross = indicators.crossover(fast, slow)
    assert list(cross) == [False, False, True, False]


def _ohlc(close: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    # Simple synthetic high/low around the close for OHLC indicators.
    return close + 1.0, close - 1.0, close


def test_macd_line_is_fast_minus_slow_ema():
    s = pd.Series(np.linspace(10, 50, 80))
    m = indicators.macd(s, fast=5, slow=13, signal=4)
    expected = indicators.ema(s, 5) - indicators.ema(s, 13)
    pd.testing.assert_series_equal(m["macd"], expected, check_names=False)
    # On a steady uptrend the fast EMA leads -> MACD line above its signal.
    assert m["macd"].iloc[-1] > m["signal"].iloc[-1]


def test_bollinger_bands_bracket_and_widen_with_std():
    s = pd.Series(np.linspace(10, 50, 60))
    b = indicators.bollinger(s, window=20, num_std=2.0)
    tail = b.dropna()
    assert (tail["lower"] <= tail["mid"]).all()
    assert (tail["mid"] <= tail["upper"]).all()
    wider = indicators.bollinger(s, window=20, num_std=3.0).dropna()
    assert (wider["upper"] >= tail["upper"]).all()


def test_true_range_and_atr_are_nonnegative():
    close = pd.Series(np.linspace(100, 120, 40))
    high, low, _ = _ohlc(close)
    tr = indicators.true_range(high, low, close)
    assert (tr >= 0).all()
    a = indicators.atr(high, low, close, window=14)
    assert a.iloc[:13].isna().all()          # warm-up
    assert (a.dropna() >= 0).all()


def test_donchian_channel_tracks_extremes_with_no_lookahead():
    close = pd.Series(np.linspace(100, 120, 30))
    high, low, _ = _ohlc(close)
    d = indicators.donchian(high, low, window=10)
    assert d.iloc[:9].isna().all().all()     # warm-up
    # Rolling max/min include the current bar, so upper>=high, lower<=low.
    tail = d.dropna()
    assert (tail["upper"] >= high.loc[tail.index]).all()
    assert (tail["lower"] <= low.loc[tail.index]).all()


def test_roc_matches_pct_change():
    s = pd.Series([100.0, 110.0, 121.0, 133.1])
    r = indicators.roc(s, window=1)
    assert r.iloc[1] == pytest.approx(10.0)
    assert r.iloc[2] == pytest.approx(10.0)
