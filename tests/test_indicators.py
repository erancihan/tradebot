import numpy as np
import pandas as pd

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
