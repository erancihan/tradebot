"""In-memory portfolio accounting used by the backtester (and handy in tests).

Tracks cash, per-symbol positions with average cost basis, and realised P&L.
Supports long and short via signed quantities. This is *simulation* accounting,
not margin/broker truth — the live path reads positions from Alpaca instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import Position, Trade, utcnow


@dataclass
class Portfolio:
    cash: float
    positions: dict[str, Position] = field(default_factory=dict)
    realized_pnl: float = 0.0
    trades: list[Trade] = field(default_factory=list)

    def position(self, symbol: str) -> Position:
        return self.positions.setdefault(symbol, Position(symbol))

    def equity(self, prices: dict[str, float]) -> float:
        """Cash plus marked-to-market value of all open positions."""
        mv = 0.0
        for sym, pos in self.positions.items():
            if not pos.is_flat:
                mv += pos.market_value(prices[sym])
        return self.cash + mv

    def gross_exposure(self, prices: dict[str, float], exclude: str | None = None) -> float:
        """Absolute market value of open positions (optionally excluding one)."""
        total = 0.0
        for sym, pos in self.positions.items():
            if sym == exclude or pos.is_flat:
                continue
            total += abs(pos.market_value(prices[sym]))
        return total

    def execute(self, symbol: str, qty_delta: float, price: float, commission: float = 0.0) -> None:
        """Apply a signed fill, updating cash, cost basis and realised P&L.

        Positive ``qty_delta`` buys; negative sells/shorts. Realised P&L is
        booked whenever an existing position is reduced or closed.
        """
        if qty_delta == 0:
            return
        pos = self.position(symbol)
        self.cash -= qty_delta * price + commission

        old_qty = pos.qty
        new_qty = old_qty + qty_delta

        closing = old_qty != 0 and (old_qty > 0) != (qty_delta > 0)
        if closing:
            closed = min(abs(qty_delta), abs(old_qty))
            direction = 1.0 if old_qty > 0 else -1.0
            pnl = (price - pos.avg_price) * closed * direction
            self.realized_pnl += pnl
            self.trades.append(
                Trade(
                    symbol=symbol,
                    qty=closed,
                    entry_price=pos.avg_price,
                    exit_price=price,
                    pnl=pnl,
                    timestamp=utcnow(),
                )
            )

        if new_qty == 0:
            pos.qty = 0.0
            pos.avg_price = 0.0
        elif (old_qty >= 0) == (new_qty >= 0) and not closing:
            # Adding to the position in the same direction -> weighted avg cost.
            pos.avg_price = (pos.avg_price * old_qty + price * qty_delta) / new_qty
            pos.qty = new_qty
        elif closing and (new_qty > 0) == (old_qty > 0):
            # Partial close, same side remains -> cost basis unchanged.
            pos.qty = new_qty
        else:
            # Flipped through zero -> the remainder opens a fresh position.
            pos.qty = new_qty
            pos.avg_price = price
