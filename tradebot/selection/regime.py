"""Composite selector that rotates between legs by market regime."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .base import Selector
from .ranked import LowVolatilitySelector, MomentumSelector, RankedSelector


class RegimeSwitchSelector(Selector):
    """Defense by *rotation*: hold momentum in calm regimes, calmest names in storms.

    Composes a :class:`MomentumSelector` and a :class:`LowVolatilitySelector` and
    switches between their verdicts based on the pool's realized volatility. In a
    calm regime the book chases the top-K trailing performers; when the pool's
    volatility spikes into a "storm" it rotates into the K *calmest* names
    instead. This is distinct from a vol-target dial, which shrinks the same
    book — here the book stays fully invested, just in different names.

    Regime proxy: the equal-weight mean of each symbol's rolling return
    volatility over ``vol_window`` bars, annualized by ``√252``. Bar ``t`` is a
    storm iff the proxy at ``t`` exceeds ``storm_vol``; during warmup the proxy
    is NaN, which counts as calm (``NaN > x`` is ``False``).

    Prefix-stable by construction: both sub-selectors are prefix-stable and the
    regime at ``t`` uses only bars ``≤ t``, so the row-wise switch reproduces any
    prefix exactly. Each leg keeps its own hysteresis walk; state is deliberately
    *not* threaded across the switch (the regime flip is the whole point).

    The legs warm up at different rates, so verdicts are held flat until the
    slower one is live — see ``membership``. Without that, a storm arriving in
    the gap would trade on the short leg alone, before the ``required_history``
    this selector advertises.
    """

    name = "regime_switch"

    def __init__(
        self,
        lookback: int = 252,
        skip: int = 21,
        top_k: int = 5,
        vol_window: int = 63,
        storm_vol: float = 0.25,
        exit_rank: int | None = None,
    ) -> None:
        if storm_vol <= 0:
            raise ValueError(f"storm_vol must be > 0, got {storm_vol}")
        self._momentum = MomentumSelector(
            lookback=lookback, skip=skip, top_k=top_k, exit_rank=exit_rank,
        )
        self._low_vol = LowVolatilitySelector(
            window=vol_window, top_k=top_k, exit_rank=exit_rank,
        )
        self.lookback = lookback
        self.skip = skip
        self.top_k = top_k
        self.vol_window = vol_window
        self.storm_vol = storm_vol
        self.exit_rank = exit_rank
        # Need the longer of the two legs warmed before either verdict is valid.
        self.required_history = max(
            self._momentum.required_history, self._low_vol.required_history,
        )

    def membership(self, frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
        calm = self._momentum.membership(frames)
        stormy = self._low_vol.membership(frames)
        if calm.empty:
            return calm
        # Both memberships share the same (sorted) index and column order because
        # each derives from the same frames via `_closes`; align defensively.
        stormy = stormy.reindex(index=calm.index, columns=calm.columns)
        is_storm = self._storm(frames).reindex(calm.index, fill_value=False).to_numpy()
        combined = np.where(is_storm[:, None], stormy.to_numpy(), calm.to_numpy())
        # One leg warms up sooner than the other, so whichever is ready first
        # would otherwise emit verdicts before `required_history` — the contract
        # this selector publishes. Hold flat until both legs are live; masking a
        # leading run of rows preserves prefix-stability.
        combined[: self.required_history - 1] = False
        return pd.DataFrame(combined, index=calm.index, columns=calm.columns)

    def _storm(self, frames: dict[str, pd.DataFrame]) -> pd.Series:
        """Boolean per-bar storm flag from the pool's annualized volatility proxy."""
        closes = RankedSelector._closes(frames)
        # Column-wise pct_change().rolling(window).std() == indicators.rolling_volatility
        # per symbol; the equal-weight mean is the pool proxy (skips warmup NaNs).
        vol = closes.pct_change().rolling(self.vol_window, min_periods=self.vol_window).std()
        proxy = vol.mean(axis=1) * np.sqrt(252.0)
        return proxy > self.storm_vol
