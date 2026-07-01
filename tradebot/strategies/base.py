"""The Strategy interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

from ..models import BAR_COLUMNS


class Strategy(ABC):
    """Base class for all strategies.

    Subclasses implement :meth:`target_positions`, returning a Series aligned to
    the input bars whose values are in {-1, 0, +1} (short / flat / long).

    The contract is deliberately strict to prevent look-ahead bias: the target
    at index ``t`` may only depend on bars at ``t`` and earlier. The backtester
    additionally shifts targets by one bar before execution, so a decision made
    on bar ``t``'s close is filled on bar ``t+1``.
    """

    #: Human-readable name used in logs and the strategy registry.
    name: str = "strategy"

    @property
    def required_history(self) -> int:
        """Minimum number of bars needed before signals are meaningful.

        The engine uses this to size its data requests for live trading.
        """
        return 50

    @abstractmethod
    def target_positions(self, bars: pd.DataFrame) -> pd.Series:
        """Return a target-position Series in {-1, 0, +1} indexed like ``bars``."""

    @staticmethod
    def _validate(bars: pd.DataFrame) -> None:
        missing = [c for c in BAR_COLUMNS if c not in bars.columns]
        if missing:
            raise ValueError(f"bars is missing required columns: {missing}")

    def latest_target(self, bars: pd.DataFrame) -> int:
        """Convenience for live trading: the most recent target as an int."""
        targets = self.target_positions(bars)
        if targets.empty:
            return 0
        value = targets.iloc[-1]
        return 0 if pd.isna(value) else int(value)
