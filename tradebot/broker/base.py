"""The Broker interface the engine talks to.

Kept deliberately small: the engine needs account equity, current positions,
whether the market is open, and the ability to place/cancel orders. Anything
broker-specific stays inside the adapter.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from ..models import Order, Position


@dataclass(frozen=True)
class AccountSnapshot:
    equity: float
    cash: float
    buying_power: float
    is_paper: bool


#: Order states a broker can report; ``unknown`` is anything it names otherwise.
ORDER_STATUSES = frozenset({"new", "partially_filled", "filled", "canceled",
                            "expired", "rejected", "unknown"})
#: States an order never leaves: a reconcile stops asking about it.
TERMINAL_STATUSES = frozenset({"filled", "canceled", "expired", "rejected"})


@dataclass(frozen=True)
class LegFill:
    """A filled bracket leg (stop or target) of an entry order: an exit the
    bot never submitted itself, logged so the offline account sees it."""
    broker_order_id: str
    side: str                 # "buy" | "sell"
    filled_qty: float
    fill_price: float
    filled_at: datetime | None


@dataclass(frozen=True)
class OrderStatus:
    """What the broker says became of one order: how much filled, at what
    average price, and when (the last two None until something filled).

    ``legs`` are its bracket legs that filled; ``legs_open`` says a leg still
    rests, so a filled parent is asked again until its bracket settles. A
    broker without brackets leaves both at their defaults."""
    status: str
    filled_qty: float
    fill_price: float | None
    filled_at: datetime | None
    legs: tuple[LegFill, ...] = ()
    legs_open: bool = False

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES


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

    def order_status(self, broker_order_id: str) -> OrderStatus | None:
        """What became of one order, or None when this broker cannot say.

        Not abstract: a broker that cannot report keeps the default, and the
        order log then shows its orders as submitted, quantity assumed."""
        return None
