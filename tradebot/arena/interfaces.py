"""Contestant-facing interfaces for the arena.

Two ways to write an algorithm:

1. **Vectorized** — subclass the existing :class:`tradebot.strategies.Strategy`
   and implement ``target_positions(bars)``. Convenient for indicator math.

2. **Event-driven** — subclass :class:`Algo` here and implement
   ``on_bar(bar, ctx)``. The algo only ever sees the *current* bar plus a
   read-only window of past bars via ``ctx``, so it physically cannot look into
   the future — the right default for a fair competition.

Both are discovered with the :func:`tradebot.arena.register` decorator and run
through the same simulation core, so they are directly comparable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple

import pandas as pd

from .. import indicators


class Bar(NamedTuple):
    """The latest OHLCV bar handed to an event-driven algo."""

    ts: pd.Timestamp
    open: float
    high: float
    low: float
    close: float
    volume: float
    symbol: str


@dataclass(frozen=True)
class Action:
    """What an event-driven algo wants its target position to be.

    ``target`` is in {-1, 0, +1} (short / flat / long), or ``None`` to *hold*
    whatever the previous target was.
    """

    target: int | None

    @classmethod
    def long(cls) -> "Action":
        return cls(1)

    @classmethod
    def short(cls) -> "Action":
        return cls(-1)

    @classmethod
    def flat(cls) -> "Action":
        return cls(0)

    @classmethod
    def hold(cls) -> "Action":
        return cls(None)


class Context:
    """Read-only view of the world passed to :meth:`Algo.on_bar`.

    Exposes the current position, account equity and a window of **past and
    present** bars only, plus a few indicator helpers computed over that window.
    There is deliberately no way to reach future data.
    """

    def __init__(self, symbol: str, window: pd.DataFrame, position, equity: float) -> None:
        self._symbol = symbol
        self._window = window
        self._position = position
        self._equity = equity

    @property
    def symbol(self) -> str:
        return self._symbol

    @property
    def bars(self) -> pd.DataFrame:
        """The full past+present window (oldest first; last row is the current bar)."""
        return self._window

    @property
    def equity(self) -> float:
        return self._equity

    @property
    def position(self):
        return self._position

    @property
    def position_qty(self) -> float:
        return self._position.qty

    @property
    def is_long(self) -> bool:
        return self._position.qty > 0

    @property
    def is_flat(self) -> bool:
        return self._position.is_flat

    # --- indicator helpers (latest value over the window) --------------------
    def sma(self, window: int) -> float:
        return float(indicators.sma(self._window["close"], window).iloc[-1])

    def ema(self, window: int) -> float:
        return float(indicators.ema(self._window["close"], window).iloc[-1])

    def rsi(self, window: int = 14) -> float:
        return float(indicators.rsi(self._window["close"], window).iloc[-1])


class Algo:
    """Base class for event-driven contestants.

    Implement :meth:`on_bar`. ``on_start`` / ``on_finish`` are optional lifecycle
    hooks. A fresh instance is created for every tournament round, so instance
    attributes are a safe place to keep per-round state.
    """

    #: Optional display name; the @register decorator can override it.
    name: str | None = None

    def on_start(self) -> None:  # noqa: D401 - optional hook
        """Called once before the first bar."""

    def on_bar(self, bar: Bar, ctx: Context) -> Action:
        raise NotImplementedError

    def on_finish(self) -> None:  # noqa: D401 - optional hook
        """Called once after the last bar."""
