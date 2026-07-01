"""Pure technical-indicator functions over pandas Series.

Everything here is side-effect free and uses only past+present data at each
index position, so the same functions are safe in both backtest and live code.
"""

from __future__ import annotations

import pandas as pd


def sma(series: pd.Series, window: int) -> pd.Series:
    """Simple moving average."""
    if window < 1:
        raise ValueError("window must be >= 1")
    return series.rolling(window=window, min_periods=window).mean()


def ema(series: pd.Series, window: int) -> pd.Series:
    """Exponential moving average (span convention, no look-ahead)."""
    if window < 1:
        raise ValueError("window must be >= 1")
    return series.ewm(span=window, adjust=False, min_periods=window).mean()


def rsi(series: pd.Series, window: int = 14) -> pd.Series:
    """Relative Strength Index using Wilder's smoothing.

    Returns values in [0, 100]; the first `window` values are NaN.
    """
    if window < 1:
        raise ValueError("window must be >= 1")
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    # Wilder's smoothing == EWM with alpha = 1/window.
    avg_gain = gain.ewm(alpha=1.0 / window, adjust=False, min_periods=window).mean()
    avg_loss = loss.ewm(alpha=1.0 / window, adjust=False, min_periods=window).mean()
    rs = avg_gain / avg_loss
    out = 100.0 - (100.0 / (1.0 + rs))
    # When avg_loss is 0, RS is +inf -> RSI 100; pandas already yields that, but
    # guard the 0/0 case (flat series) explicitly as neutral 50.
    out = out.where(~((avg_gain == 0) & (avg_loss == 0)), 50.0)
    return out


def crossover(fast: pd.Series, slow: pd.Series) -> pd.Series:
    """True at bars where `fast` crosses from <= to > `slow`."""
    prev = fast.shift(1) <= slow.shift(1)
    now = fast > slow
    return (prev & now).fillna(False)


def crossunder(fast: pd.Series, slow: pd.Series) -> pd.Series:
    """True at bars where `fast` crosses from >= to < `slow`."""
    prev = fast.shift(1) >= slow.shift(1)
    now = fast < slow
    return (prev & now).fillna(False)
