"""The selector interface: a membership verdict per symbol per bar."""

from __future__ import annotations

from abc import ABC, abstractmethod

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
