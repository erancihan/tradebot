"""Replay a fixed history bar-by-bar to drive an offline dry-run.

``ReplayData`` exposes the same ``history()`` method the engine expects, but only
reveals bars up to an internal cursor. The cursor is advanced explicitly by the
caller (one step per loop iteration) via :meth:`advance`, so every ``history()``
call within a single rebalance pass sees a stable window. This turns a dry-run
into a deterministic, zero-credential forward-test — ideal for tests and demos.
"""

from __future__ import annotations

import pandas as pd


class ReplayData:
    def __init__(self, frames: dict[str, pd.DataFrame], warmup: int = 1) -> None:
        if not frames:
            raise ValueError("ReplayData needs at least one symbol frame")
        self._frames = frames
        self._max = min(len(df) for df in frames.values())
        if self._max < 2:
            raise ValueError("Replay frames need at least 2 bars")
        # Number of bars currently visible; start with enough to warm up signals.
        self.cursor = max(1, min(warmup, self._max))

    @classmethod
    def from_single(cls, df: pd.DataFrame, symbol: str = "ASSET", warmup: int = 1) -> "ReplayData":
        return cls({symbol: df}, warmup=warmup)

    def history(self, symbol: str, timeframe: str | None = None, lookback: int | None = None) -> pd.DataFrame:
        try:
            df = self._frames[symbol]
        except KeyError:
            raise KeyError(f"No replay data for symbol {symbol!r}") from None
        return df.iloc[: self.cursor]

    def has_next(self) -> bool:
        return self.cursor < self._max

    def advance(self, n: int = 1) -> int:
        self.cursor = min(self.cursor + n, self._max)
        return self.cursor

    @property
    def progress(self) -> tuple[int, int]:
        return (self.cursor, self._max)
