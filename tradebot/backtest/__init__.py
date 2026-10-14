"""Backtesting: the vectorised loop, its result type and the shared bar steps.

The private helpers are re-exported because the arena's stepped loop, walk-
forward and the tests import them from here.
"""

from __future__ import annotations

from .result import BacktestResult, _infer_periods_per_year
from .runner import Backtester
from .steps import _prepare_components, _sizing_marks

__all__ = ["Backtester", "BacktestResult"]
