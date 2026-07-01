"""The Broker interface the engine talks to.

Kept deliberately small: the engine needs account equity, current positions,
whether the market is open, and the ability to place/cancel orders. Anything
broker-specific stays inside the adapter.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..models import Order, Position


@dataclass(frozen=True)
class AccountSnapshot:
    equity: float
    cash: float
    buying_power: float
    is_paper: bool


class Broker(ABC):
    @abstractmethod
    def account(self) -> AccountSnapshot: ...

    @abstractmethod
    def positions(self) -> dict[str, Position]: ...

    @abstractmethod
    def position(self, symbol: str) -> Position: ...

    @abstractmethod
    def is_market_open(self) -> bool: ...

    @abstractmethod
    def submit(self, order: Order) -> str:
        """Place an order; return the broker order id."""

    @abstractmethod
    def cancel_all(self) -> None: ...
