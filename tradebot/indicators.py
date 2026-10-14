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


def rolling_volatility(close: pd.Series, window: int) -> pd.Series:
    """Rolling standard deviation of simple (close-to-close) returns.

    NaN until a full ``window`` of returns is available, so downstream code can
    tell "not enough history" apart from "genuinely low volatility".
    """
    if window < 1:
        raise ValueError("window must be >= 1")
    returns = close.pct_change()
    return returns.rolling(window=window, min_periods=window).std()


def macd(
    close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """MACD: returns (macd_line, signal_line, histogram).

    macd_line = EMA(fast) - EMA(slow); signal_line = EMA(macd_line, signal);
    histogram = macd_line - signal_line. NaN until each smoothing is warm.
    """
    if not 0 < fast < slow:
        raise ValueError(f"require 0 < fast < slow, got {fast}, {slow}")
    if signal < 1:
        raise ValueError("signal must be >= 1")
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return macd_line, signal_line, macd_line - signal_line


def bollinger_bands(
    close: pd.Series, window: int = 20, num_std: float = 2.0
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Bollinger bands: returns (middle, upper, lower).

    middle = SMA(window); upper/lower = middle +/- num_std rolling stdevs.
    NaN until a full window is available.
    """
    if window < 2:
        raise ValueError("window must be >= 2")
    if num_std <= 0:
        raise ValueError("num_std must be > 0")
    middle = sma(close, window)
    std = close.rolling(window=window, min_periods=window).std(ddof=0)
    return middle, middle + num_std * std, middle - num_std * std


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


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """Wilder's True Range: max(H-L, |H-prevC|, |L-prevC|) per bar.

    The first bar (no previous close) falls back to H-L.
    """
    prev_close = close.shift(1)
    ranges = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    )
    return ranges.max(axis=1)


def atr(
    high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14
) -> pd.Series:
    """Average True Range via Wilder's smoothing (EWM with alpha = 1/window).

    The first ``window`` values are NaN. Look-ahead safe (only past+present).
    """
    if window < 1:
        raise ValueError("window must be >= 1")
    tr = true_range(high, low, close)
    return tr.ewm(alpha=1.0 / window, adjust=False, min_periods=window).mean()


def donchian(high: pd.Series, low: pd.Series, window: int = 20) -> pd.DataFrame:
    """Donchian channel: rolling ``window`` high/low and their midpoint.

    Returns columns ``upper``, ``lower``, ``mid``. Note the channel *includes*
    the current bar; breakout strategies should ``shift(1)`` to compare the
    current bar against the *prior* window (no look-ahead).
    """
    if window < 1:
        raise ValueError("window must be >= 1")
    upper = high.rolling(window=window, min_periods=window).max()
    lower = low.rolling(window=window, min_periods=window).min()
    return pd.DataFrame({"upper": upper, "lower": lower, "mid": (upper + lower) / 2.0})


def roc(series: pd.Series, window: int = 10) -> pd.Series:
    """Rate of change over ``window`` bars, in percent. First ``window`` NaN."""
    if window < 1:
        raise ValueError("window must be >= 1")
    return series.pct_change(periods=window) * 100.0
