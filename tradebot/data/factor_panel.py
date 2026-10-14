"""Jointly generated synthetic pools: one shared market factor, many names.

Split from :mod:`tradebot.data.synthetic` (which re-exports it). The random draws
happen in a fixed order — the whole factor path first, then per symbol its
idiosyncratic returns, intrabar noise and volume — so a given seed always
reproduces the same pool.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..models import BAR_COLUMNS


def synthetic_factor_panel(
    symbols: dict[str, dict],
    regimes: list[dict],
    start: str = "2023-01-02",
    freq: str = "1D",
    start_price: float = 100.0,
    seed: int | None = 42,
) -> dict[str, pd.DataFrame]:
    """Generate a whole pool *jointly* from one shared market factor.

    The existing generators draw each symbol independently, which is the wrong
    null for testing cross-sectional machinery: with near-zero pairwise
    correlation a "crash" is several unrelated accidents, every name is a haven,
    and diversification is free. Measured on the shipped `cross_sectional.yaml`,
    mean pairwise return correlation is ~0.03 — and on its seed the designated
    laggard outperforms the designated leader, so the scenario labelled "this is
    where selection matters" does not reliably contain the thing selection is
    meant to find.

    Here one factor path is drawn per bar and every symbol loads on it::

        F_t        ~ N(drift_seg, vol_seg)                 # one shared path
        beta_s,t   = beta_s + beta_shift_seg * (1 - beta_s)  # crisis contagion
        r_s,t      = alpha_s,seg + beta_s,t * F_t + N(0, idio_s)

    ``symbols`` maps name -> ``{"beta": float, "alpha": float | list[float],
    "idio_vol": float}``. A list-valued ``alpha`` gives one value per regime
    segment, which is how a leadership reversal is expressed. ``beta_shift`` on
    a segment drags every beta toward 1.0, the standard crisis behaviour where
    correlations converge and a haven stops working.

    Returns one frame per symbol, all sharing an index. OHLC is built exactly as
    in :func:`synthetic_ohlcv` so the two are comparable.
    """
    if not symbols:
        raise ValueError("need at least one symbol")
    if not regimes:
        raise ValueError("regimes must be a non-empty list of segments")

    rng = np.random.default_rng(seed)
    factor, vols, shifts, segs = _factor_path(regimes, rng)
    n = len(factor)
    index = pd.date_range(start=start, periods=n, freq=freq, tz="UTC")

    out: dict[str, pd.DataFrame] = {}
    for name, spec in symbols.items():
        beta = float(spec.get("beta", 1.0))
        idio = float(spec.get("idio_vol", 0.008))
        alpha = _alpha_path(name, spec.get("alpha", 0.0), len(regimes), segs, n)
        betas = beta + shifts * (1.0 - beta)
        rets = alpha + betas * factor + rng.normal(0.0, idio, size=n)
        out[name] = _ohlcv(rets, vols + idio, start_price, index, rng)
    return out


def _factor_path(regimes: list[dict], rng: np.random.Generator):
    """The shared factor path plus per-bar vol, beta shift and segment number."""
    factor_parts, vol_parts, shift_parts, seg_index = [], [], [], []
    for i, seg in enumerate(regimes):
        periods = int(seg.get("periods", 0))
        if periods < 1:
            raise ValueError(f"regime segment needs periods >= 1, got {seg!r}")
        drift = float(seg.get("drift", 0.0004))
        volatility = float(seg.get("volatility", 0.012))
        factor_parts.append(rng.normal(loc=drift, scale=volatility, size=periods))
        vol_parts.append(np.full(periods, volatility))
        shift_parts.append(np.full(periods, float(seg.get("beta_shift", 0.0))))
        seg_index.append(np.full(periods, i))
    return (np.concatenate(factor_parts), np.concatenate(vol_parts),
            np.concatenate(shift_parts), np.concatenate(seg_index))


def _alpha_path(name: str, alpha_spec, n_regimes: int, segs: np.ndarray, n: int) -> np.ndarray:
    """Per-bar alpha: a scalar, or one value per regime segment."""
    if isinstance(alpha_spec, (list, tuple)):
        if len(alpha_spec) != n_regimes:
            raise ValueError(
                f"{name}: alpha list has {len(alpha_spec)} entries for "
                f"{n_regimes} regime segments")
        return np.asarray(alpha_spec, dtype=float)[segs]
    return np.full(n, float(alpha_spec))


def _ohlcv(rets: np.ndarray, noise_vol: np.ndarray, start_price: float,
           index: pd.DatetimeIndex, rng: np.random.Generator) -> pd.DataFrame:
    """OHLCV around a log-return path, built as in ``synthetic_ohlcv``."""
    n = len(rets)
    close = start_price * np.exp(np.cumsum(rets))
    prev_close = np.concatenate([[start_price], close[:-1]])
    open_ = prev_close
    noise = np.abs(rng.normal(0, noise_vol / 2)) * close
    return pd.DataFrame(
        {"open": open_,
         "high": np.maximum(open_, close) + noise,
         "low": np.minimum(open_, close) - noise,
         "close": close,
         "volume": rng.integers(1_000_000, 5_000_000, size=n).astype(float)},
        index=index,
    )[list(BAR_COLUMNS)]
