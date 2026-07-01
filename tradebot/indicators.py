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


def macd(
    series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> pd.DataFrame:
    """MACD: (fast EMA - slow EMA), its signal EMA, and the histogram.

    Returns a frame with columns ``macd``, ``signal``, ``hist`` aligned to
    ``series``. Uses only past+present data (EMAs), so it is look-ahead safe.
    """
    if min(fast, slow, signal) < 1:
        raise ValueError("macd windows must be >= 1")
    if fast >= slow:
        raise ValueError(f"fast ({fast}) must be < slow ({slow})")
    macd_line = ema(series, fast) - ema(series, slow)
    signal_line = ema(macd_line, signal)
    return pd.DataFrame(
        {"macd": macd_line, "signal": signal_line, "hist": macd_line - signal_line}
    )


def bollinger(
    series: pd.Series, window: int = 20, num_std: float = 2.0
) -> pd.DataFrame:
    """Bollinger Bands: middle SMA plus ``num_std`` population-std envelopes.

    Returns a frame with columns ``mid``, ``upper``, ``lower``. The first
    ``window`` values are NaN (SMA/std warm-up).
    """
    if window < 2:
        raise ValueError("window must be >= 2")
    if num_std <= 0:
        raise ValueError("num_std must be > 0")
    mid = sma(series, window)
    # ddof=0 (population std) is the conventional Bollinger definition.
    std = series.rolling(window=window, min_periods=window).std(ddof=0)
    return pd.DataFrame(
        {"mid": mid, "upper": mid + num_std * std, "lower": mid - num_std * std}
    )


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
