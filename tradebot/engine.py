"""Live/paper trading engine.

One ``rebalance()`` pass per symbol:
  1. pull recent bars and current account/position from the broker,
  2. ask the strategy for the latest target regime,
  3. size it with the RiskManager (respecting per-position and gross caps),
  4. submit the difference as a market order and persist it.

The same Strategy + RiskManager objects power the backtester, so behaviour is
consistent between simulation and live. A daily-loss circuit breaker flattens
and stops trading for the session once breached.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass

from .broker.base import Broker
from .config import Settings
from .models import Order, Side
from .risk import RiskManager
from .storage import Storage
from .strategies.base import Strategy

log = logging.getLogger("tradebot.engine")


@dataclass
class RebalanceAction:
    symbol: str
    target: int
    current_qty: float
    desired_qty: float
    order_qty: float          # signed; 0 means no action
    submitted_id: str | None = None


class Engine:
    def __init__(
        self,
        settings: Settings,
        broker: Broker,
        data_source,                 # object with .history(symbol, timeframe, lookback)
        strategy: Strategy,
        risk: RiskManager,
        storage: Storage | None = None,
        mode_label: str | None = None,
        enforce_live_ack: bool = True,
    ) -> None:
        # The live gate is skipped for dry-runs (no real broker can be reached).
        if enforce_live_ack:
            settings.require_live_ack()  # hard gate before anything can trade
        self.settings = settings
        self.broker = broker
        self.data = data_source
        self.strategy = strategy
        self.risk = risk
        self.storage = storage
        # Label used for logs and storage tagging (e.g. "dry_run").
        self._mode_label = mode_label or settings.mode
        self._session_start_equity: float | None = None

    @property
    def mode(self) -> str:
        return self._mode_label

    def _lookback_days(self) -> int:
        # Ensure enough history for the strategy plus headroom for weekends/holidays.
        return max(self.strategy.required_history * 2, 60)

    def rebalance_symbol(self, symbol: str, equity: float, other_gross: float) -> RebalanceAction:
        bars = self.data.history(
            symbol, timeframe=self.settings.timeframe, lookback=self._lookback_days()
        )
        if self.storage is not None:
            # Persist the price history (idempotent) so the dashboard can chart it.
            self.storage.record_bars(symbol, self.settings.timeframe, bars, self.mode)
        target = self.strategy.latest_target(bars)
        price = float(bars["close"].iloc[-1])

        current = self.broker.position(symbol).qty
        desired = self.risk.target_qty(target, equity, price)
        delta = desired - current

        increasing = (current == 0) or ((current > 0) == (delta > 0))
        if increasing and delta != 0:
            delta = self.risk.clamp_to_exposure(delta, price, equity, other_gross)

        if not self.risk.config.allow_fractional:
            delta = float(round(delta))

        action = RebalanceAction(
            symbol=symbol,
            target=target,
            current_qty=current,
            desired_qty=desired,
            order_qty=delta,
        )
        if delta == 0:
            log.info("%s: target=%d, holding %.4f shares (no order)", symbol, target, current)
            return action

        order = Order(symbol=symbol, qty=abs(delta), side=Side.from_delta(delta))
        action.submitted_id = self.broker.submit(order)
        log.info(
            "%s: target=%d, %s %.4f @~%.2f (order %s)",
            symbol, target, order.side.value, abs(delta), price, action.submitted_id,
        )
        if self.storage:
            self.storage.record_order(order, action.submitted_id, self.mode)
        return action

    def rebalance(self) -> list[RebalanceAction]:
        """One full pass across all configured symbols."""
        if not self.broker.is_market_open():
            log.info("Market closed; skipping rebalance.")
            return []

        acct = self.broker.account()
        if self._session_start_equity is None:
            self._session_start_equity = acct.equity
        if self.storage:
            self.storage.record_equity(acct.equity, acct.cash, self.mode)

        # Circuit breaker: stop opening risk if today's drawdown is too deep.
        if self.risk.daily_loss_tripped(self._session_start_equity, acct.equity):
            log.warning(
                "Daily loss limit hit (start=%.2f now=%.2f). Flattening and halting.",
                self._session_start_equity, acct.equity,
            )
            self.broker.cancel_all()
            return []

        positions = self.broker.positions()
        actions: list[RebalanceAction] = []
        for sym in self.settings.symbols:
            other_gross = sum(
                abs(p.qty) * p.avg_price for s, p in positions.items() if s != sym
            )
            try:
                actions.append(self.rebalance_symbol(sym, acct.equity, other_gross))
            except Exception:  # one bad symbol shouldn't kill the whole pass
                log.exception("Rebalance failed for %s", sym)
        return actions

    def run_forever(self, max_iterations: int | None = None) -> None:
        log.info(
            "Starting engine: mode=%s symbols=%s strategy=%s every %ss",
            self.mode, self.settings.symbols, self.strategy.name, self.settings.poll_seconds,
        )
        i = 0
        while max_iterations is None or i < max_iterations:
            try:
                self.rebalance()
            except Exception:
                log.exception("Rebalance pass errored; continuing.")
            i += 1
            if max_iterations is not None and i >= max_iterations:
                break
            time.sleep(self.settings.poll_seconds)
