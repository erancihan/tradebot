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
from .models import Order, Side, opens_exposure
from .notify import LogNotifier
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
        """Full accumulated per-symbol history for the selector.

        The strategy is stateless over a bounded window, so the fetched frames
        are fine for it. A `RankedSelector` is not: its hysteresis walk carries
        `held` from an empty set, so a verdict depends on where the frame
        *starts*. Feeding it the rolling fetch window made live selection depend
        on process start time and diverge from the backtest that validated it.

        Every fetched bar is already persisted just above, so the store holds a
        superset of the window. Without a store (or before any history has
        accumulated) we fall back to the fetched frames — same behaviour as
        before, and the only honest option when there is nothing else to read.
        """
        if self.storage is None:
            return fetched
        out: dict[str, object] = {}
        for sym, window in fetched.items():
            try:
                stored = self.storage.load_bars(sym, self.settings.timeframe, self.mode)
            except Exception:
                log.exception("Could not read stored bars for %s; using the fetch window", sym)
                stored = None
            out[sym] = stored if stored is not None and len(stored) >= len(window) else window
        return out

    def _notify(self, event: dict) -> None:
        """Emit an observability event. A notifier can never break a trade pass."""
        try:
            self.notifier.send({"mode": self.mode, **event})
        except Exception:
            log.exception("Notifier failed for event %s", event.get("type"))

    def _check_brackets(self) -> None:
        """Let a simulating broker fire its resting stops/targets for this bar.

        Duck-typed on purpose: a real broker holds the bracket legs itself and
        exposes no such hook, so this is a no-op live and the `Broker` ABC stays
        as small as it was.
        """
        check = getattr(self.broker, "check_brackets", None)
        if check is None:
            return
        try:
            fills = check() or []
        except Exception:
            log.exception("Bracket check failed; continuing the pass")
            return
        for fill in fills:
            self._notify({
                "type": "bracket_exit", "symbol": fill.symbol,
                "qty": fill.qty, "price": fill.price,
                "ts": fill.timestamp.isoformat(),
            })

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
        current = self.broker.position(symbol).qty
        delta = self.risk.material_delta(desired, current, price, equity)
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

        # Brackets ride on entries only: a reduction is already an exit, and
        # attaching a stop to it would rest an exit against a position that is
        # on its way out.
        stop = target_price = None
        if opens_exposure(current, delta):
            stop, target_price = self.risk.bracket_prices(delta, price)

        order = Order(symbol=symbol, qty=abs(delta), side=Side.from_delta(delta),
                      stop_loss=stop, take_profit=target_price)
        action.submitted_id = self.broker.submit(order)
        log.info(
            "%s: target=%d, %s %.4f @~%.2f (order %s)%s",
            symbol, target, order.side.value, abs(delta), price, action.submitted_id,
            f" bracket stop={stop:.2f}" if stop else "",
        )
        if self.storage:
            self.storage.record_order(order, action.submitted_id, self.mode)
        self._notify({
            "type": "order", "symbol": symbol, "side": order.side.value,
            "qty": abs(delta), "price": price, "target": target,
            "order_id": action.submitted_id,
            "stop_loss": stop, "take_profit": target_price,
        })
        return action

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

        # Circuit breaker: stop opening risk if today's drawdown is too deep.
        if self.risk.daily_loss_tripped(self._session_start_equity, acct.equity):
            log.warning(
                "Daily loss limit hit (start=%.2f now=%.2f). Flattening and halting.",
                self._session_start_equity, acct.equity,
            )
            self.broker.cancel_all()
            self._notify({
                "type": "halt", "reason": "daily_loss",
                "start_equity": self._session_start_equity, "equity": acct.equity,
                "limit_pct": self.risk.config.max_daily_loss_pct,
            })
            return []

        # 1) Gather bars, latest target and price per symbol. A failing symbol
        #    drops out of this pass instead of killing it.
        frames: dict[str, object] = {}
        targets: dict[str, int] = {}
        prices: dict[str, float] = {}
        for sym in self.settings.symbols:
            try:
                bars = self.data.history(
                    sym, timeframe=self.settings.timeframe, lookback=self._lookback_days()
                )
                if self.storage is not None:
                    # Persist the price history (idempotent) for the dashboard.
                    self.storage.record_bars(sym, self.settings.timeframe, bars, self.mode)
                price = float(bars["close"].iloc[-1])
                if not math.isfinite(price) or price <= 0:
                    raise ValueError(f"no valid price for {sym} (got {price})")
                targets[sym] = self.strategy.latest_target(bars)
                prices[sym] = price
                frames[sym] = bars
            except Exception:
                log.exception("Data/signal failed for %s; skipping it this pass", sym)

        # 2) Cross-sectional gate: symbols outside the selection are forced
        #    flat. Membership is recomputed every pass from the FULL accumulated
        #    history (bars are the only state), not from the bounded window the
        #    strategy uses — see `_selector_frames`.
        if self.selector is not None:
            membership = self.selector.latest_targets(self._selector_frames(frames))
            for sym in targets:
                if not membership.get(sym):
                    targets[sym] = 0

        # 3) Size the whole book at once (order-independent). Live decisions
        #    use bars up to now, same as the strategy's latest_target.
        weights = None
        if self.allocator is not None:
            weights = self.allocator.weights(targets, frames)
            for overlay in self.overlays:
                weights = overlay.transform(weights, targets, frames)
            if self.storage:
                # Post-overlay: what the book actually targets.
                self.storage.record_weights(weights, self.mode)
        desired = self.risk.allocate(targets, acct.equity, prices, weights)

        # 4) Submit the deltas.
        actions: list[RebalanceAction] = []
        for sym in targets:
            try:
                actions.append(
                    self._submit_delta(sym, targets[sym], desired[sym],
                                       prices[sym], acct.equity)
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
