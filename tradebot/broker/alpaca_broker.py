"""Alpaca broker adapter (``alpaca-py``), paper-trading by default.

Safety: live trading is refused unless ``paper=False`` is passed *and* the
caller has gone through the config gate (see config.Settings.require_live_ack).
The SDK is imported lazily so the package imports fine without it.
"""

from __future__ import annotations

from ..models import Order, OrderType, Position, Side, TimeInForce
from .base import AccountSnapshot, Broker

PAPER_ENDPOINT = "https://paper-api.alpaca.markets"
LIVE_ENDPOINT = "https://api.alpaca.markets"


class AlpacaBroker(Broker):
    def __init__(self, api_key: str, api_secret: str, paper: bool = True) -> None:
        from alpaca.trading.client import TradingClient

        self.paper = paper
        self._client = TradingClient(api_key, api_secret, paper=paper)

    # --- account / positions -------------------------------------------------
    def account(self) -> AccountSnapshot:
        a = self._client.get_account()
        return AccountSnapshot(
            equity=float(a.equity),
            cash=float(a.cash),
            buying_power=float(a.buying_power),
            is_paper=self.paper,
        )

    def positions(self) -> dict[str, Position]:
        out: dict[str, Position] = {}
        for p in self._client.get_all_positions():
            out[p.symbol] = Position(
                symbol=p.symbol,
                qty=float(p.qty),
                avg_price=float(p.avg_entry_price),
            )
        return out

    def position(self, symbol: str) -> Position:
        return self.positions().get(symbol, Position(symbol))

    def is_market_open(self) -> bool:
        return bool(self._client.get_clock().is_open)

    # --- orders --------------------------------------------------------------
    def submit(self, order: Order) -> str:
        from alpaca.trading.enums import OrderSide as AOrderSide
        from alpaca.trading.enums import TimeInForce as ATif
        from alpaca.trading.requests import LimitOrderRequest, MarketOrderRequest

        side = AOrderSide.BUY if order.side is Side.BUY else AOrderSide.SELL
        tif = ATif.DAY if order.time_in_force is TimeInForce.DAY else ATif.GTC

        if order.type is OrderType.LIMIT:
            req = LimitOrderRequest(
                symbol=order.symbol,
                qty=order.qty,
                side=side,
                time_in_force=tif,
                limit_price=order.limit_price,
                client_order_id=order.client_order_id,
            )
        else:
            req = MarketOrderRequest(
                symbol=order.symbol,
                qty=order.qty,
                side=side,
                time_in_force=tif,
                client_order_id=order.client_order_id,
            )
        submitted = self._client.submit_order(req)
        return str(submitted.id)

    def cancel_all(self) -> None:
        self._client.cancel_orders()
