"""Cross-sectional selection: decide *which* symbols may be held.

A :class:`Selector` looks at the whole candidate pool at once — something a
per-symbol ``Strategy`` deliberately cannot do — and produces a membership
verdict per symbol per bar. Membership *gates* the strategy signal (a symbol
outside the selection is forced flat); it never sizes anything, so the layering
stays strategy → selector gate → allocator weights → RiskManager quantities.

Selection must be prefix-stable (no look-ahead): the verdict at bar ``t`` may
depend only on bars ``≤ t`` and on earlier verdicts, so recomputing over any
prefix of history reproduces that prefix exactly. That property is what lets
the live engine simply recompute from full fetched history every pass (bars
are the source of truth — same pattern as the arena season) and what the
backtester's one-bar shift relies on.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import numpy as np
import pandas as pd


class Selector(ABC):
    """Base class for cross-sectional selectors."""

    #: Name used in config (`portfolio.selector.name`) and logs.
    name: str = "selector"

    #: Bars needed before the selector can produce a verdict.
    required_history: int = 1

    @abstractmethod
    def membership(self, frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
        """Boolean membership matrix (index = bars, columns = symbols).

        ``True`` at ``(t, s)`` means the selector wants ``s`` holdable based on
        data ``≤ t``. Must be prefix-stable.
        """

    def latest_targets(self, frames: dict[str, pd.DataFrame]) -> dict[str, int]:
        """Convenience for live trading: the most recent verdict per symbol."""
        member = self.membership(frames)
        if member.empty:
            return {s: 0 for s in frames}
        last = member.iloc[-1]
        return {s: int(bool(last.get(s, False))) for s in frames}


class RankedSelector(Selector):
    """Shared machinery: score the pool each bar, hold the top-K with hysteresis.

    Subclasses implement :meth:`scores` (higher = better). Each bar the best
    ``top_k`` are held; a current holding is only dropped once its rank slips
    below ``exit_rank`` (default 1.5×K), so names hovering at the boundary
    don't churn in and out every bar. Symbols with a NaN score are
    unmeasurable and never selected — don't hold what you can't rank.
    The walk is causal (bar ``t`` uses scores at ``t`` and earlier verdicts),
    so every subclass is prefix-stable by construction.
    """

    def __init__(self, top_k: int, exit_rank: int | None) -> None:
        if top_k < 1:
            raise ValueError(f"top_k must be >= 1, got {top_k}")
        if exit_rank is None:
            exit_rank = top_k + max(top_k // 2, 1)
        if exit_rank < top_k:
            raise ValueError(f"exit_rank ({exit_rank}) must be >= top_k ({top_k})")
        self.top_k = top_k
        self.exit_rank = exit_rank

    @abstractmethod
    def scores(self, frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
        """Score matrix (index = bars, columns = symbols); higher = better."""

    def membership(self, frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
        scores = self.scores(frames)
        held: set[str] = set()
        rows: list[dict[str, bool]] = []
        for _, row in scores.iterrows():
            ranked = self._rank(row)
            rank_of = {s: r + 1 for r, s in enumerate(ranked)}
            keep = {s for s in held if rank_of.get(s, np.inf) <= self.exit_rank}
            for s in ranked:
                if len(keep) >= self.top_k:
                    break
                keep.add(s)
            held = keep
            rows.append({s: s in keep for s in scores.columns})
        return pd.DataFrame(rows, index=scores.index, columns=scores.columns)

    @staticmethod
    def _rank(row: pd.Series) -> list[str]:
        """Symbols by descending score; ties broken alphabetically (determinism)."""
        valid = row.dropna()
        return sorted(valid.index, key=lambda s: (-valid[s], s))

    @staticmethod
    def _closes(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
        return pd.DataFrame({s: f["close"] for s, f in frames.items()}).sort_index()


class MomentumSelector(RankedSelector):
    """Classic cross-sectional momentum: hold the top-K trailing performers.

    Each bar, candidates are scored by their ``lookback``-bar return *skipping*
    the most recent ``skip`` bars (the standard "12-1" construction — recent
    bars are excluded to dodge short-term reversal).

    ``reverse=True`` flips the ranking to hold the biggest *losers* — the
    short-term reversal construction (use a short lookback, e.g.
    ``lookback=15, skip=1``, where mean reversion dominates momentum).
    """

    name = "momentum"

    def __init__(
        self,
        lookback: int = 252,
        skip: int = 21,
        top_k: int = 5,
        exit_rank: int | None = None,
        reverse: bool = False,
    ) -> None:
        super().__init__(top_k, exit_rank)
        if lookback <= skip:
            raise ValueError(f"lookback ({lookback}) must exceed skip ({skip})")
        if skip < 0:
            raise ValueError(f"skip must be >= 0, got {skip}")
        self.lookback = lookback
        self.skip = skip
        self.reverse = reverse
        self.required_history = lookback + 1

    def scores(self, frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
        """Momentum score matrix: return from bar ``t-lookback`` to ``t-skip``."""
        closes = self._closes(frames)
        momentum = closes.shift(self.skip) / closes.shift(self.lookback) - 1.0
        return -momentum if self.reverse else momentum


class LowVolatilitySelector(RankedSelector):
    """Low-volatility anomaly: hold the K calmest names.

    Scores each symbol by (negated) realized volatility of close-to-close
    returns over ``window`` bars, so the *least* volatile names rank best.
    """

    name = "low_vol"

    def __init__(
        self,
        window: int = 63,
        top_k: int = 5,
        exit_rank: int | None = None,
    ) -> None:
        super().__init__(top_k, exit_rank)
        if window < 2:
            raise ValueError(f"window must be >= 2, got {window}")
        self.window = window
        self.required_history = window + 1

    def scores(self, frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
        closes = self._closes(frames)
        vol = closes.pct_change().rolling(self.window, min_periods=self.window).std()
        return -vol


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


SELECTORS: dict[str, type[Selector]] = {
    MomentumSelector.name: MomentumSelector,
    LowVolatilitySelector.name: LowVolatilitySelector,
    RegimeSwitchSelector.name: RegimeSwitchSelector,
}


def build_selector(name: str, params: dict[str, Any] | None = None) -> Selector:
    """Instantiate a selector by name with keyword params from config."""
    try:
        cls = SELECTORS[name]
    except KeyError:
        known = ", ".join(sorted(SELECTORS))
        raise KeyError(f"Unknown selector {name!r}. Known: {known}") from None
    return cls(**(params or {}))
