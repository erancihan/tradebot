"""Supertrend: an ATR-based adaptive trend follower.

Bands are placed ``multiplier`` * ATR above/below the bar midpoint and then
"ratcheted" (a band can only tighten toward price, never loosen, until price
closes through it). The trend flips long when the close crosses above the trailing
upper band and short when it crosses below the trailing lower band. Long when the
trend is up; flat (or short, if enabled) when it is down.

This indicator is inherently recursive — each bar's bands depend on the previous
bar's — so it is computed with an explicit forward pass over numpy arrays. It reads
only past+present data (ATR and the current/previous close), so there is no
look-ahead. During the ATR warm-up the trend is undefined and the target is flat.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .. import indicators
from .base import Strategy


class Supertrend(Strategy):
    name = "supertrend"

    def __init__(
        self,
        period: int = 10,
        multiplier: float = 3.0,
        allow_short: bool = False,
    ) -> None:
        if period < 1:
            raise ValueError(f"period ({period}) must be >= 1")
        if multiplier <= 0:
            raise ValueError(f"multiplier ({multiplier}) must be > 0")
        self.period = period
        self.multiplier = multiplier
        self.allow_short = allow_short

    @property
    def required_history(self) -> int:
        return self.period * 3

    def target_positions(self, bars: pd.DataFrame) -> pd.Series:
        self._validate(bars)
        high, low, close = bars["high"], bars["low"], bars["close"]
        atr = indicators.atr(high, low, close, self.period).to_numpy()
        hl2 = ((high + low) / 2.0).to_numpy()
        close_a = close.to_numpy()

        basic_upper = hl2 + self.multiplier * atr
        basic_lower = hl2 - self.multiplier * atr

        n = len(close_a)
        direction = np.zeros(n, dtype="int64")  # +1 up, -1 down, 0 warm-up
        final_upper = np.full(n, np.nan)
        final_lower = np.full(n, np.nan)

        started = False
        prev_dir = 0
        for i in range(n):
            if np.isnan(atr[i]):
                continue  # ATR warm-up: trend undefined -> flat
            if not started:
                # Seed the trailing bands and pick an initial trend from the close.
                final_upper[i] = basic_upper[i]
                final_lower[i] = basic_lower[i]
                prev_dir = 1 if close_a[i] >= basic_lower[i] else -1
                direction[i] = prev_dir
                started = True
                continue

            # Ratchet the bands: they only move toward price unless price has
            # already closed beyond them on the previous bar.
            final_upper[i] = (
                basic_upper[i]
                if (basic_upper[i] < final_upper[i - 1] or close_a[i - 1] > final_upper[i - 1])
                else final_upper[i - 1]
            )
            final_lower[i] = (
                basic_lower[i]
                if (basic_lower[i] > final_lower[i - 1] or close_a[i - 1] < final_lower[i - 1])
                else final_lower[i - 1]
            )

            if prev_dir == 1:  # was up: flip down only on a close below the lower band
                prev_dir = -1 if close_a[i] < final_lower[i] else 1
            else:              # was down: flip up only on a close above the upper band
                prev_dir = 1 if close_a[i] > final_upper[i] else -1
            direction[i] = prev_dir

        target = pd.Series(direction, index=bars.index, dtype="int64")
        if not self.allow_short:
            target[target < 0] = 0
        return target
