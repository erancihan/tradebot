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
from dataclasses import dataclass

from ..models import Fill, Side, opens_exposure, utcnow
from ..portfolio import Portfolio
from .base import AccountSnapshot, Broker

log = logging.getLogger("tradebot.dryrun")


@dataclass
class _Bracket:
    """Resting exit levels attached to an open dry-run position."""

    stop: float | None
    target: float | None
    entry: float


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
        self._brackets: dict[str, _Bracket] = {}

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
        before = self.portfolio.position(order.symbol).qty
        slip = self.slippage_bps / 10_000.0
        fill_price = price * (1 + slip) if signed > 0 else price * (1 - slip)
        self.portfolio.execute(order.symbol, signed, fill_price, commission=self.commission)
        self._track_bracket(order, before, fill_price)

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

    # --- brackets ------------------------------------------------------------
    def _track_bracket(self, order, qty_before: float, fill_price: float) -> None:
        """Attach/refresh/drop the resting exit levels after a simulated fill.

        Only fills that *increase* exposure carry a bracket, matching the engine
        seam: a reduction is already an exit and does not need protecting. A
        fill that flattens or flips the position drops the old bracket, so a
        stale level can never fire against a position it was never sized for.
        """
        after = self.portfolio.position(order.symbol).qty
        if abs(after) < 1e-9 or after * qty_before < 0:
            self._brackets.pop(order.symbol, None)
        if not opens_exposure(qty_before, after - qty_before):
            return
        if getattr(order, "has_bracket", False):
            self._brackets[order.symbol] = _Bracket(
                stop=order.stop_loss, target=order.take_profit, entry=fill_price
            )

    def _latest_bar(self, symbol: str):
        bars = self.data.history(
            symbol, timeframe=self.timeframe, lookback=self.mark_lookback
        )
        if bars is None or len(bars) == 0:
            return None
        return bars.iloc[-1]

    def check_brackets(self) -> list[Fill]:
        """Fire any resting stop/target hit by the latest bar; return the exits.

        Deterministic and deliberately pessimistic:
        - the **stop wins** when one bar touches both levels (we cannot see the
          intrabar path, so we assume the worse ordering);
        - a bar that *gaps through* a stop fills at the open, not at the stop
          price — a stop is a trigger, not a guaranteed price;
        - a target never fills better than its limit, even on a favourable gap.

        Duck-typed rather than added to the `Broker` ABC: brackets are resting
        orders the real broker manages itself, so only the simulator needs a
        polling hook. The engine calls it via `getattr` and skips it otherwise.
        """
        exits: list[Fill] = []
        for symbol, bracket in list(self._brackets.items()):
            pos = self.portfolio.position(symbol)
            if pos.is_flat:
                self._brackets.pop(symbol, None)
                continue
            bar = self._latest_bar(symbol)
            if bar is None:
                continue
            high, low, open_ = float(bar["high"]), float(bar["low"]), float(bar["open"])
            long = pos.qty > 0

            price = None
            if bracket.stop is not None and (
                (long and low <= bracket.stop) or (not long and high >= bracket.stop)
            ):
                price = min(bracket.stop, open_) if long else max(bracket.stop, open_)
                reason = "stop_loss"
            elif bracket.target is not None and (
                (long and high >= bracket.target) or (not long and low <= bracket.target)
            ):
                price = bracket.target
                reason = "take_profit"
            if price is None:
                continue

            qty = -pos.qty                      # close the whole position
            self.portfolio.execute(symbol, qty, price, commission=self.commission)
            self._brackets.pop(symbol, None)
            self._marks[symbol] = price
            log.info(
                "[DRY-RUN] %s FIRED %s %.4f @ %.2f (entry %.2f)",
                reason.upper(), symbol, abs(qty), price, bracket.entry,
            )
            exits.append(Fill(symbol=symbol, qty=qty, price=price,
                              commission=self.commission, timestamp=utcnow()))
        return exits

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
