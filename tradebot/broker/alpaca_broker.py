"""Alpaca broker adapter (``alpaca-py``), paper-trading by default.

Safety: live trading is refused unless ``paper=False`` is passed *and* the
caller has gone through the config gate (see config.Settings.require_live_ack).
The SDK is imported lazily so the package imports fine without it.
"""

from __future__ import annotations

import logging
import time

from ..models import EQUITY, Order, OrderType, Position, Side, TimeInForce
from .base import (ORDER_STATUSES, TERMINAL_STATUSES, AccountSnapshot, Broker, LegFill,
                   OrderStatus)

log = logging.getLogger("tradebot.broker")

PAPER_ENDPOINT = "https://paper-api.alpaca.markets"
LIVE_ENDPOINT = "https://api.alpaca.markets"

#: Alpaca states that mean "still working": accepted but not yet done.
_OPEN_STATES = frozenset({"accepted", "pending_new", "accepted_for_bidding", "held",
                          "calculated", "pending_cancel", "pending_replace",
                          # Paused, not over: the order may still trade later.
                          "done_for_day", "stopped", "suspended"})
#: Alpaca states that end the order: ``replaced`` means a new order took over.
_GONE_STATES = {"replaced": "canceled"}


def _status(order) -> str:
    raw = str(getattr(order.status, "value", order.status) or "").lower()
    return (raw if raw in ORDER_STATUSES else "new" if raw in _OPEN_STATES
            else _GONE_STATES.get(raw, "unknown"))


def map_order_status(order) -> OrderStatus:
    """An SDK ``Order`` as our :class:`OrderStatus` (duck-typed: no SDK import).

    Alpaca's status is an enum whose ``value`` is the wire string; one of ours
    passes through, a working or paused state is ``new``, ``replaced`` is
    ``canceled`` (the original order is gone), anything else ``unknown``.
    A bracket's legs (``nested``) come back as the filled ones, plus whether
    one still works: Alpaca fills a stop or target without the bot asking."""
    filled = float(order.filled_qty or 0.0)
    price = order.filled_avg_price
    legs = list(getattr(order, "legs", None) or [])
    done = [leg for leg in legs if float(leg.filled_qty or 0.0) > 0
            and leg.filled_avg_price is not None and _status(leg) == "filled"]
    return OrderStatus(
        status=_status(order), filled_qty=filled,
        fill_price=float(price) if price is not None and filled else None,
        filled_at=order.filled_at,
        legs=tuple(LegFill(str(leg.id), str(getattr(leg.side, "value", leg.side)).lower(),
                           float(leg.filled_qty), float(leg.filled_avg_price),
                           leg.filled_at) for leg in done),
        legs_open=any(_status(leg) not in TERMINAL_STATUSES for leg in legs))


class AlpacaBroker(Broker):
    def __init__(self, api_key: str, api_secret: str, paper: bool = True) -> None:
        from alpaca.trading.client import TradingClient

        self.paper = paper
        self._client = TradingClient(api_key, api_secret, paper=paper)

    #: A read that failed on the wire is tried once more after this pause: a
    #: DNS blip on the clock call must not fail a whole pass. A submit is never
    #: retried (a second send could double an order).
    RETRY_SECONDS = 2.0
    _sleep = staticmethod(time.sleep)

    def _read(self, call):
        """``call()``, once more after a connection error (requests' errors
        are ``OSError``s; an Alpaca API error is not and propagates at once)."""
        try:
            return call()
        except OSError as exc:  # noqa: PERF203 - one retry, then the error is the pass's
            log.warning("Alpaca read failed (%s); retrying in %ss",
                        type(exc).__name__, self.RETRY_SECONDS)
            self._sleep(self.RETRY_SECONDS)
            return call()

    # --- account / positions -------------------------------------------------
    def account(self) -> AccountSnapshot:
        a = self._read(self._client.get_account)
        return AccountSnapshot(
            equity=float(a.equity),
            cash=float(a.cash),
            buying_power=float(a.buying_power),
            is_paper=self.paper,
        )

    def positions(self) -> dict[str, Position]:
        out: dict[str, Position] = {}
        for p in self._read(self._client.get_all_positions):
            kind = getattr(p, "asset_class", None)
            out[p.symbol] = Position(
                symbol=p.symbol,
                qty=float(p.qty),
                avg_price=float(p.avg_entry_price),
                asset_class=str(getattr(kind, "value", kind) or EQUITY),
            )
        return out

    def position(self, symbol: str) -> Position:
        return self.positions().get(symbol, Position(symbol))

    def is_market_open(self) -> bool:
        return bool(self._read(self._client.get_clock).is_open)

    # --- orders --------------------------------------------------------------
    @staticmethod
    def _bracket_kwargs(order: Order) -> dict:
        """Map our absolute bracket prices onto Alpaca's order classes.

        Both legs -> ``bracket``; one leg -> ``oto`` (Alpaca rejects a bracket
        that is missing a side). Nothing is inferred here: the engine already
        resolved the offsets to prices, so this stays a pure translation.
        """
        if not order.has_bracket:
            return {}
        from alpaca.trading.enums import OrderClass
        from alpaca.trading.requests import StopLossRequest, TakeProfitRequest

        legs: dict = {}
        if order.stop_loss is not None:
            legs["stop_loss"] = StopLossRequest(stop_price=round(order.stop_loss, 2))
        if order.take_profit is not None:
            legs["take_profit"] = TakeProfitRequest(limit_price=round(order.take_profit, 2))
        order_class = OrderClass.BRACKET if len(legs) == 2 else OrderClass.OTO
        return {"order_class": order_class, **legs}

    def submit(self, order: Order) -> str:
        from alpaca.trading.enums import OrderSide as AOrderSide
        from alpaca.trading.enums import TimeInForce as ATif
        from alpaca.trading.requests import LimitOrderRequest, MarketOrderRequest

        side = AOrderSide.BUY if order.side is Side.BUY else AOrderSide.SELL
        tif = ATif.DAY if order.time_in_force is TimeInForce.DAY else ATif.GTC
        bracket = self._bracket_kwargs(order)

        if order.type is OrderType.LIMIT:
            req = LimitOrderRequest(
                symbol=order.symbol,
                qty=order.qty,
                side=side,
                time_in_force=tif,
                limit_price=order.limit_price,
                client_order_id=order.client_order_id,
                **bracket,
            )
        else:
            req = MarketOrderRequest(
                symbol=order.symbol,
                qty=order.qty,
                side=side,
                time_in_force=tif,
                client_order_id=order.client_order_id,
                **bracket,
            )
        submitted = self._client.submit_order(req)
        return str(submitted.id)

    def order_status(self, broker_order_id: str) -> OrderStatus | None:
        """One order's state with its bracket legs; an SDK error propagates
        (the reconciler logs it)."""
        from alpaca.trading.requests import GetOrderByIdRequest

        return map_order_status(self._read(lambda: self._client.get_order_by_id(
            broker_order_id, filter=GetOrderByIdRequest(nested=True))))

    def cancel_all(self) -> None:
        self._client.cancel_orders()
