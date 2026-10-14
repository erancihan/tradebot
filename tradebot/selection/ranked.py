"""Rank-the-pool selectors: hold the top-K by score, with hysteresis."""

from __future__ import annotations

from abc import abstractmethod

import numpy as np
import pandas as pd

from .base import Selector


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
            # A held name must stay droppable whenever the pool is bigger than
            # `top_k`. The default `exit_rank` (top_k + max(top_k//2, 1)) can
            # reach or exceed the pool size — e.g. 3 for top_k=2 on three names —
            # and then every held name is permanently inside it and membership
            # FREEZES at the first verdict. That silently made the whole real
            # gauntlet inert: momentum picked one pair and held it for 587 bars.
            exit_rank = min(self.exit_rank, max(len(ranked) - 1, self.top_k))
            keep = {s for s in held if rank_of.get(s, np.inf) <= exit_rank}
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
        """Close matrix on the *intersection* of the per-symbol indexes.

        `pd.DataFrame({...})` aligns on the UNION, which inserts a NaN close for
        any symbol missing a session and so blanks that symbol's score for a
        whole rolling window — it becomes unrankable and cannot be held. Both
        execution loops align on the intersection, and only the live engine ever
        passes ragged frames, so unioning here is a pure backtest-vs-live
        divergence that no offline fixture can show (they all share an index).
        """
        if not frames:
            return pd.DataFrame()
        common = None
        for f in frames.values():
            common = f.index if common is None else common.intersection(f.index)
        common = common.sort_values()
        return pd.DataFrame({s: f["close"].reindex(common) for s, f in frames.items()})


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
