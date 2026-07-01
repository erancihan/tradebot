"""Adapt both contestant interfaces to a single ``Policy`` the sim core drives.

A ``Policy`` answers one question per bar: *given the window of data up to now,
what target position (-1/0/+1) do you want for this symbol?* — and can be reset
to a fresh state between rounds.
"""

from __future__ import annotations

from typing import Protocol

import pandas as pd

from .contestant import Contestant
from .interfaces import Action, Algo, Bar, Context


class Policy(Protocol):
    def reset(self) -> None: ...

    def decide(self, symbol: str, window: pd.DataFrame, position, equity: float) -> int: ...


class VectorizedPolicy:
    """Wraps a ``Strategy``; asks for the target of the window's final bar."""

    def __init__(self, factory) -> None:
        self._factory = factory
        self._strategy = None

    def reset(self) -> None:
        self._strategy = self._factory()

    def decide(self, symbol: str, window: pd.DataFrame, position, equity: float) -> int:
        return self._strategy.latest_target(window)


class EventPolicy:
    """Wraps an ``Algo``; calls ``on_bar`` with a look-ahead-safe context."""

    def __init__(self, factory) -> None:
        self._factory = factory
        self._algo: Algo | None = None
        self._last: dict[str, int] = {}

    def reset(self) -> None:
        self._algo = self._factory()
        self._last = {}
        self._algo.on_start()

    def decide(self, symbol: str, window: pd.DataFrame, position, equity: float) -> int:
        row = window.iloc[-1]
        bar = Bar(
            ts=window.index[-1],
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["volume"]),
            symbol=symbol,
        )
        ctx = Context(symbol, window, position, equity)
        result = self._algo.on_bar(bar, ctx)

        last = self._last.get(symbol, 0)
        if result is None:
            return last
        target = result.target if isinstance(result, Action) else result
        if target is None:  # explicit hold
            return last
        target = max(-1, min(1, int(target)))
        self._last[symbol] = target
        return target


def policy_for(contestant: Contestant) -> Policy:
    if contestant.kind == "vectorized":
        return VectorizedPolicy(contestant.factory)
    if contestant.kind == "event":
        return EventPolicy(contestant.factory)
    raise ValueError(f"Unknown contestant kind: {contestant.kind!r}")
