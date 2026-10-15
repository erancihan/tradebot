"""Round trips and realised P&L from one account's fills (average cost).

Per symbol, a position opens on its first fill and scales in at the average
price. A fill against it realises ``(exit - avg) * qty_closed`` (sign flipped
for a short) and leaves the average unchanged. A trip closes when the position
returns to flat; a fill that crosses zero closes the trip and opens the next
one with the remainder at the fill's price. What is still open has no P&L
here: the ledger holds no prices, only the realised part so far.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .models import Fill, Trade

_EPS = 1e-9


@dataclass
class OpenTrade:
    """A position still open at the end of the fills, at its average cost."""

    symbol: str
    side: str                 # "long" or "short"
    qty: float                # absolute shares held
    avg_price: float
    entry_ts: datetime
    realised: float = 0.0     # from partial exits so far


@dataclass
class _Trip:
    symbol: str
    long: bool                # the side the trip was built on (it ends flat)
    entry_ts: datetime
    qty: float = 0.0          # signed, as held
    avg: float = 0.0
    opened: float = 0.0       # shares bought (long) or sold (short) to build it
    cost: float = 0.0         # their notional
    closed: float = 0.0
    proceeds: float = 0.0
    realised: float = 0.0

    def add(self, qty: float, price: float) -> None:
        size = abs(self.qty) + abs(qty)
        self.avg = (self.avg * abs(self.qty) + price * abs(qty)) / size
        self.qty += qty
        self.opened += abs(qty)
        self.cost += price * abs(qty)

    def reduce(self, qty: float, price: float) -> float:
        """Close up to ``|qty|`` shares; returns the signed shares left over."""
        direction = 1.0 if self.qty > 0 else -1.0
        shares = min(abs(qty), abs(self.qty))
        self.realised += (price - self.avg) * shares * direction
        self.closed += shares
        self.proceeds += price * shares
        self.qty -= direction * shares
        return qty + direction * shares

    def trade(self, exit_ts: datetime) -> Trade:
        return Trade(symbol=self.symbol, qty=self.opened, entry_price=self.cost / self.opened,
                     exit_price=self.proceeds / self.closed, pnl=self.realised,
                     timestamp=exit_ts, entry_ts=self.entry_ts, side=self._side())

    def still_open(self) -> OpenTrade:
        return OpenTrade(symbol=self.symbol, side=self._side(), qty=abs(self.qty),
                         avg_price=self.avg, entry_ts=self.entry_ts, realised=self.realised)

    def _side(self) -> str:
        return "long" if self.long else "short"


def _open(fill: Fill, qty: float) -> _Trip:
    trip = _Trip(fill.symbol, long=qty > 0, entry_ts=fill.timestamp)
    trip.add(qty, fill.price)
    return trip


def book(fills: list[Fill]) -> tuple[list[Trade], list[OpenTrade]]:
    """Closed trips in closing order, and what is still open (by symbol).
    ``fills`` come in time order, as ``filled_orders`` reads them."""
    trips: dict[str, _Trip] = {}
    closed: list[Trade] = []
    for fill in fills:
        qty, trip = float(fill.qty), trips.get(fill.symbol)
        if abs(qty) < _EPS:
            continue
        if trip is None:
            trips[fill.symbol] = _open(fill, qty)
            continue
        if (trip.qty > 0) == (qty > 0):
            trip.add(qty, fill.price)
            continue
        left = trip.reduce(qty, fill.price)
        if abs(trip.qty) < _EPS:
            closed.append(trip.trade(fill.timestamp))
            del trips[fill.symbol]
            if abs(left) > _EPS:                   # crossed zero: the rest opens anew
                trips[fill.symbol] = _open(fill, left)
    return closed, [trips[s].still_open() for s in sorted(trips)]


def round_trips(fills: list[Fill]) -> list[Trade]:
    """Every closed trip (open -> flat), oldest close first."""
    return book(fills)[0]


def open_trades(fills: list[Fill]) -> list[OpenTrade]:
    return book(fills)[1]


def summary(trades: list[Trade]) -> dict:
    """Counts and money over closed trips. A break-even trip is neither a win
    nor a loss; ``profit_factor`` (gross wins over gross losses) is None
    without a loss, and the averages are None without a trip of that kind."""
    wins = [t.pnl for t in trades if t.pnl > 0]
    losses = [t.pnl for t in trades if t.pnl < 0]
    pnls = [t.pnl for t in trades]
    return {
        "closed": len(trades), "wins": len(wins), "losses": len(losses),
        "win_rate": len(wins) / len(trades) if trades else None,
        "realised": sum(pnls),
        "avg_win": sum(wins) / len(wins) if wins else None,
        "avg_loss": sum(losses) / len(losses) if losses else None,
        "best": max(pnls) if pnls else None,
        "worst": min(pnls) if pnls else None,
        "profit_factor": sum(wins) / -sum(losses) if losses else None,
    }


def fills_from_orders(rows: list[dict]) -> list[Fill]:
    """Order-log rows with a known fill (``storage.orders.filled_orders``) as
    signed fills at the broker's average price. Alpaca charges no commission."""
    fills = []
    for row in rows:
        qty = float(row["filled_qty"])
        stamp = row.get("filled_at") or row["ts"]
        fills.append(Fill(symbol=row["symbol"], qty=qty if row["side"] == "buy" else -qty,
                          price=float(row["fill_price"]),
                          timestamp=datetime.fromisoformat(stamp)))
    return fills
