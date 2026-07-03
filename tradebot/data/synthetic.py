"""Offline data helpers: a synthetic OHLCV generator and a CSV loader.

These let you backtest and run the test suite with zero network access and zero
credentials — useful for development and CI.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..models import BAR_COLUMNS


def synthetic_ohlcv(
    periods: int = 500,
    start: str = "2023-01-02",
    freq: str = "1D",
    start_price: float = 100.0,
    drift: float = 0.0004,
    volatility: float = 0.012,
    seed: int | None = 42,
) -> pd.DataFrame:
    """Generate a geometric-random-walk OHLCV frame for testing/demos.

    `drift` is per-bar log-return mean, `volatility` its std. Returns a frame
    indexed by a tz-aware DatetimeIndex with open/high/low/close/volume columns.
    """
    rng = np.random.default_rng(seed)
    rets = rng.normal(loc=drift, scale=volatility, size=periods)
    close = start_price * np.exp(np.cumsum(rets))

    # Build OHLC around the close path with small intrabar noise.
    prev_close = np.concatenate([[start_price], close[:-1]])
    open_ = prev_close
    noise = np.abs(rng.normal(0, volatility / 2, size=periods)) * close
    high = np.maximum(open_, close) + noise
    low = np.minimum(open_, close) - noise
    volume = rng.integers(1_000_000, 5_000_000, size=periods).astype(float)

    index = pd.date_range(start=start, periods=periods, freq=freq, tz="UTC")
    df = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=index,
    )
    return df[list(BAR_COLUMNS)]


def synthetic_regime_ohlcv(
    regimes: list[dict],
    start: str = "2023-01-02",
    freq: str = "1D",
    start_price: float = 100.0,
    seed: int | None = 42,
) -> pd.DataFrame:
    """Concatenate random-walk segments with different drift/volatility.

    Each regime is ``{"periods": int, "drift": float, "volatility": float}``
    (drift/volatility default to :func:`synthetic_ohlcv`'s values). The price
    path is continuous across boundaries — a crash regime starts exactly where
    the calm one ended — so regime-switch scenarios (crash/recovery, vol
    spikes) stay reproducible and offline.
    """
    if not regimes:
        raise ValueError("regimes must be a non-empty list of segments")
    rng = np.random.default_rng(seed)
    rets_parts: list[np.ndarray] = []
    vol_parts: list[np.ndarray] = []
    for seg in regimes:
        periods = int(seg.get("periods", 0))
        if periods < 1:
            raise ValueError(f"regime segment needs periods >= 1, got {seg!r}")
        drift = float(seg.get("drift", 0.0004))
        volatility = float(seg.get("volatility", 0.012))
        rets_parts.append(rng.normal(loc=drift, scale=volatility, size=periods))
        vol_parts.append(np.full(periods, volatility))
    rets = np.concatenate(rets_parts)
    vols = np.concatenate(vol_parts)
    close = start_price * np.exp(np.cumsum(rets))

    # Same OHLC construction as synthetic_ohlcv, with per-bar noise scale so
    # intrabar ranges widen in the high-vol regimes too.
    prev_close = np.concatenate([[start_price], close[:-1]])
    open_ = prev_close
    noise = np.abs(rng.normal(0, vols / 2)) * close
    high = np.maximum(open_, close) + noise
    low = np.minimum(open_, close) - noise
    volume = rng.integers(1_000_000, 5_000_000, size=len(rets)).astype(float)

    index = pd.date_range(start=start, periods=len(rets), freq=freq, tz="UTC")
    df = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=index,
    )
    return df[list(BAR_COLUMNS)]


def load_csv(path: str, timestamp_col: str = "timestamp") -> pd.DataFrame:
    """Load an OHLCV CSV into the canonical bar DataFrame shape."""
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    ts = timestamp_col.lower()
    if ts not in df.columns:
        raise ValueError(f"CSV missing timestamp column {timestamp_col!r}")
    df[ts] = pd.to_datetime(df[ts], utc=True)
    df = df.set_index(ts).sort_index()
    missing = [c for c in BAR_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"CSV missing OHLCV columns: {missing}")
    return df[list(BAR_COLUMNS)]
