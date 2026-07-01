"""Core value objects shared across the bot.

Market data is passed around as pandas DataFrames (index = tz-aware timestamps,
columns = open/high/low/close/volume) because that is the natural shape for
vectorised indicator math. The dataclasses here describe the *discrete events*
of trading: signals, orders, fills and positions.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone

# Canonical column names for an OHLCV bar DataFrame.
BAR_COLUMNS = ("open", "high", "low", "close", "volume")


def utcnow() -> datetime:
    """A timezone-aware 'now' so timestamps are unambiguous in storage/logs."""
    return datetime.now(timezone.utc)


class Side(enum.Enum):
    BUY = "buy"
    SELL = "sell"

    @classmethod
    def from_delta(cls, qty_delta: float) -> "Side":
        return cls.BUY if qty_delta > 0 else cls.SELL


class OrderType(enum.Enum):
    MARKET = "market"
    LIMIT = "limit"


class TimeInForce(enum.Enum):
    DAY = "day"
    GTC = "gtc"


# Target position expressed as a regime, independent of account size.
#   +1 -> fully long, 0 -> flat, -1 -> fully short.
# Strategies emit these; the RiskManager turns them into share quantities.
class Target(enum.IntEnum):
    SHORT = -1
    FLAT = 0
    LONG = 1


@dataclass(frozen=True)
class Order:
    symbol: str
    qty: float
    side: Side
    type: OrderType = OrderType.MARKET
    time_in_force: TimeInForce = TimeInForce.DAY
    limit_price: float | None = None
    client_order_id: str | None = None
    created_at: datetime = field(default_factory=utcnow)

    def __post_init__(self) -> None:
        if self.qty <= 0:
            raise ValueError(f"Order qty must be positive, got {self.qty}")
        if self.type is OrderType.LIMIT and self.limit_price is None:
            raise ValueError("LIMIT order requires a limit_price")


@dataclass(frozen=True)
class Fill:
    symbol: str
    qty: float          # signed: +long, -short/sell
    price: float
    commission: float = 0.0
    timestamp: datetime = field(default_factory=utcnow)


@dataclass
class Position:
    symbol: str
    qty: float = 0.0
    avg_price: float = 0.0

    @property
    def is_flat(self) -> bool:
        return abs(self.qty) < 1e-9

    def market_value(self, price: float) -> float:
        return self.qty * price

    def unrealized_pnl(self, price: float) -> float:
        return (price - self.avg_price) * self.qty


@dataclass
class Trade:
    """A realised round-trip leg (a reduction/close of a position)."""

    symbol: str
    qty: float          # absolute quantity closed
    entry_price: float
    exit_price: float
    pnl: float
    timestamp: datetime = field(default_factory=utcnow)

    @property
    def is_win(self) -> bool:
        return self.pnl > 0
