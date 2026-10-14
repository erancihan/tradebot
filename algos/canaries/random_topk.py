"""Canary: pick K names at random each bar.

Not a trading idea. This is the null model for cross-sectional selection. It
must land mid-pack: if random picking beats a real momentum book on the mean,
the scenario contains no learnable cross-sectional signal and any ranking
derived from it is noise dressed as a result.

Expected position in the bracket: **mid-pack, below real candidates**.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from tradebot.allocation import EqualWeight
from tradebot.arena import PortfolioAlgo, register
from tradebot.selection import RankedSelector, Selector
from tradebot.strategies import BuyAndHold


class RandomTopKSelector(Selector):
    """Uniformly random K-of-N per bar, reproducibly.

    Prefix-stable by construction: bar ``t``'s draw is seeded from ``(seed, t)``
    where ``t`` is the bar's *position*, so recomputing over any prefix
    reproduces that prefix exactly. Seeding from a global RNG walked in order
    would also be prefix-stable, but position-seeding survives the frame being
    rebuilt, which is what the engine actually does.
    """

    name = "random_topk"

    def __init__(self, top_k: int = 2, seed: int = 20260725) -> None:
        if top_k < 1:
            raise ValueError(f"top_k must be >= 1, got {top_k}")
        self.top_k = top_k
        self.seed = seed
        self.required_history = 2

    def membership(self, frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
        closes = RankedSelector._closes(frames)
        if closes.empty:
            return pd.DataFrame(columns=list(frames))
        symbols = list(closes.columns)
        k = min(self.top_k, len(symbols))
        rows = []
        for position in range(len(closes)):
            rng = np.random.default_rng((self.seed, position))
            chosen = set(rng.choice(len(symbols), size=k, replace=False).tolist())
            rows.append({s: i in chosen for i, s in enumerate(symbols)})
        return pd.DataFrame(rows, index=closes.index, columns=symbols)


@register(name="random_topk", author="canary", tags=("canary", "diagnostic"),
          family="canary")
class RandomTopK(PortfolioAlgo):
    """Coin-flip selection. Must land mid-pack, never near the top."""

    def __init__(self) -> None:
        super().__init__(
            strategy=BuyAndHold(),
            selector=RandomTopKSelector(top_k=2),
            allocator=EqualWeight(),
        )
