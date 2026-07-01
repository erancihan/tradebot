"""Dry-run broker: a virtual account that simulates fills but never sends orders.

This implements the same :class:`Broker` interface the live engine uses, so the
engine code is unchanged — it just trades against an in-memory
:class:`~tradebot.portfolio.Portfolio` instead of Alpaca. Orders are "filled" at
the latest available price (from the same data source the engine reads) plus a
configurable slippage, so positions and P&L evolve over time. Nothing here ever
touches the network or a real account.

Use it for a free, real-time forward-test of the full pipeline:
``tradebot run --config config.yaml --dry-run``.
"""

from __future__ import annotations

import logging

from ..models import Side
from ..portfolio import Portfolio
from .base import AccountSnapshot, Broker

log = logging.getLogger("tradebot.dryrun")


class DryRunBroker(Broker):
    def __init__(
        self,
        data_source,                 # object with .history(symbol, timeframe, lookback)
        timeframe: str = "1day",
        initial_cash: float = 10_000.0,
        slippage_bps: float = 1.0,
        commission: float = 0.0,
        mark_lookback: int = 10,
    ) -> None:
        self.portfolio = Portfolio(cash=initial_cash)
        self.initial_cash = initial_cash
        self.data = data_source
        self.timeframe = timeframe
        self.slippage_bps = slippage_bps
        self.commission = commission
        self.mark_lookback = mark_lookback
        self._marks: dict[str, float] = {}
        self._order_seq = 0

    # --- price marking -------------------------------------------------------
    def _latest_price(self, symbol: str) -> float | None:
        bars = self.data.history(
            symbol, timeframe=self.timeframe, lookback=self.mark_lookback
        )
        if bars is None or len(bars) == 0:
            return self._marks.get(symbol)
        price = float(bars["close"].iloc[-1])
        self._marks[symbol] = price
        return price

    def _current_prices(self) -> dict[str, float]:
        """Latest marks for every open position (falls back to cost basis)."""
        prices: dict[str, float] = {}
        for sym, pos in self.portfolio.positions.items():
            if pos.is_flat:
                continue
            mark = self._latest_price(sym)
            prices[sym] = mark if mark is not None else pos.avg_price
        return prices

    # --- Broker interface ----------------------------------------------------
    def account(self) -> AccountSnapshot:
        equity = self.portfolio.equity(self._current_prices())
        cash = self.portfolio.cash
        return AccountSnapshot(
            equity=equity,
            cash=cash,
            buying_power=max(cash, 0.0),
            is_paper=True,
        )

    def positions(self) -> dict:
        return {
            sym: pos
            for sym, pos in self.portfolio.positions.items()
            if not pos.is_flat
        }

    def position(self, symbol: str):
        return self.portfolio.position(symbol)

    def is_market_open(self) -> bool:
        # Dry-run always "acts"; off-hours it simply runs on the latest bar.
        return True

    def submit(self, order) -> str:
        price = self._latest_price(order.symbol)
        if price is None:
            raise RuntimeError(
                f"No price available to simulate a fill for {order.symbol}"
            )
        signed = order.qty if order.side is Side.BUY else -order.qty
        slip = self.slippage_bps / 10_000.0
        fill_price = price * (1 + slip) if signed > 0 else price * (1 - slip)
        self.portfolio.execute(order.symbol, signed, fill_price, commission=self.commission)

        self._order_seq += 1
        order_id = f"dryrun-{self._order_seq}"
        log.info(
            "[DRY-RUN] SIM FILL %s %.4f %s @ %.2f (no order sent)",
            order.side.value, order.qty, order.symbol, fill_price,
        )
        return order_id

    def cancel_all(self) -> None:
        # No resting orders exist in dry-run; nothing to cancel.
        pass

    # --- reporting -----------------------------------------------------------
    def summary(self) -> dict:
        pf = self.portfolio
        equity = pf.equity(self._current_prices())
        trades = pf.trades
        wins = sum(1 for t in trades if t.is_win)
        open_pos = ", ".join(
            f"{s}:{p.qty:g}@{p.avg_price:.2f}"
            for s, p in pf.positions.items()
            if not p.is_flat
        )
        return {
            "initial_cash": round(self.initial_cash, 2),
            "final_equity": round(equity, 2),
            "total_return": round(equity / self.initial_cash - 1, 4) if self.initial_cash else 0.0,
            "realized_pnl": round(pf.realized_pnl, 2),
            "cash": round(pf.cash, 2),
            "num_trades": len(trades),
            "win_rate": round(wins / len(trades), 4) if trades else 0.0,
            "open_positions": open_pos or "none",
        }
