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
import time

from ..broker.base import Broker
from ..config import Settings
from ..notify import LogNotifier
from ..risk import RiskManager
from ..storage import Storage
from ..strategies.base import Strategy
from . import orders, signals
from .orders import RebalanceAction

log = logging.getLogger("tradebot.engine")


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
        allocator=None,              # optional tradebot.allocation.Allocator
        selector=None,               # optional tradebot.selection.Selector
        overlays=None,               # optional list of tradebot.overlays.Overlay
        notifier=None,               # optional tradebot.notify.Notifier
    ) -> None:
        # The live gate is skipped for dry-runs (no real broker can be reached).
        if enforce_live_ack:
            settings.require_live_ack()  # hard gate before anything can trade
        if overlays and allocator is None:
            raise ValueError("overlays require an allocator (they transform its weights)")
        self.settings = settings
        self.broker = broker
        self.data = data_source
        self.strategy = strategy
        self.risk = risk
        self.storage = storage
        self.allocator = allocator
        self.selector = selector
        self.overlays = list(overlays or [])
        self.notifier = notifier or LogNotifier()
        # Label used for logs and storage tagging (e.g. "dry_run").
        self._mode_label = mode_label or settings.mode
        self._session_start_equity: float | None = None

    @property
    def mode(self) -> str:
        return self._mode_label

    def _selector_frames(self, fetched: dict[str, object]) -> dict[str, object]:
        return signals.selector_frames(self, fetched)

    def _notify(self, event: dict) -> None:
        """Emit an observability event. A notifier can never break a trade pass."""
        try:
            self.notifier.send({"mode": self.mode, **event})
        except Exception:
            log.exception("Notifier failed for event %s", event.get("type"))

    def _check_brackets(self) -> None:
        orders.check_brackets(self)

    def _lookback_days(self) -> int:
        # Ensure enough history for every history-hungry component (strategy,
        # selector, allocator, overlays) plus headroom for weekends/holidays.
        needed = self.strategy.required_history
        for component in (self.selector, self.allocator, *self.overlays):
            if component is not None:
                needed = max(needed, component.required_history)
        return max(needed * 2, 60)

    def _submit_delta(
        self, symbol: str, target: int, desired: float, price: float, equity: float
    ) -> RebalanceAction:
        return orders.submit_delta(self, symbol, target, desired, price, equity)

    def rebalance(self) -> list[RebalanceAction]:
        """One full pass: gather signals for all symbols, size the book
        jointly, then submit the per-symbol deltas."""
        if not self.broker.is_market_open():
            log.info("Market closed; skipping rebalance.")
            return []

        # Before anything reads the account: a stop that fired on this bar has
        # to be booked first, or sizing would be done against stale equity.
        self._check_brackets()

        acct = self.broker.account()
        if self._session_start_equity is None:
            self._session_start_equity = acct.equity
        if self.storage:
            self.storage.record_equity(acct.equity, acct.cash, self.mode)
        if self._halt_on_daily_loss(acct.equity):
            return []

        frames, targets, prices = self._gather_signals()
        self._apply_selector(frames, targets)
        desired = self._size_book(frames, targets, prices, acct.equity)
        return self._submit_all(targets, desired, prices, acct.equity)

    def _halt_on_daily_loss(self, equity: float) -> bool:
        """Circuit breaker: stop opening risk if today's drawdown is too deep."""
        if not self.risk.daily_loss_tripped(self._session_start_equity, equity):
            return False
        log.warning(
            "Daily loss limit hit (start=%.2f now=%.2f). Flattening and halting.",
            self._session_start_equity, equity,
        )
        self.broker.cancel_all()
        self._notify({
            "type": "halt", "reason": "daily_loss",
            "start_equity": self._session_start_equity, "equity": equity,
            "limit_pct": self.risk.config.max_daily_loss_pct,
        })
        return True

    def _gather_signals(self):
        return signals.gather_signals(self)

    def _apply_selector(self, frames: dict[str, object], targets: dict[str, int]) -> None:
        """Force symbols outside the selection flat, in place.

        Membership is recomputed every pass from the FULL accumulated history
        (bars are the only state), not from the bounded window the strategy
        uses — see `_selector_frames`.
        """
        if self.selector is None:
            return
        membership = self.selector.latest_targets(self._selector_frames(frames))
        for sym in targets:
            if not membership.get(sym):
                targets[sym] = 0

    def _size_book(self, frames, targets: dict[str, int], prices: dict[str, float],
                   equity: float) -> dict[str, float]:
        """Size the whole book at once (order-independent). Live decisions use
        bars up to now, same as the strategy's latest_target."""
        weights = None
        if self.allocator is not None:
            weights = self.allocator.weights(targets, frames)
            for overlay in self.overlays:
                weights = overlay.transform(weights, targets, frames)
            if self.storage:
                # Post-overlay: what the book actually targets.
                self.storage.record_weights(weights, self.mode)
        return self.risk.allocate(targets, equity, prices, weights)

    def _submit_all(self, targets: dict[str, int], desired: dict[str, float],
                    prices: dict[str, float], equity: float) -> list[RebalanceAction]:
        actions: list[RebalanceAction] = []
        for sym in targets:
            try:
                actions.append(
                    self._submit_delta(sym, targets[sym], desired[sym], prices[sym], equity)
                )
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
