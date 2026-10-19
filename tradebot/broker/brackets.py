"""Simulated resting bracket legs for the dry-run broker.

A real broker holds stop/target legs itself; the simulator has to fire them
from each bar's high/low. Kept apart from the fill/account logic so the
pessimistic fill rules live in one readable place.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ..models import Fill, opens_exposure, utcnow

log = logging.getLogger("tradebot.dryrun")


@dataclass
class _Bracket:
    """Resting exit levels attached to an open dry-run position."""

    stop: float | None
    target: float | None
    entry: float
    # Timestamp of the bar the entry filled on. That bar's high/low include
    # prices from before the fill, so only a strictly later bar may fire a leg.
    entry_bar: object = None
    # The entry order's id: a fired leg's own id derives from it.
    entry_id: str | None = None


def exit_price(bracket: _Bracket, high: float, low: float, open_: float,
               long: bool) -> tuple[float | None, str | None]:
    """The fill price and reason if this bar triggers a leg, else ``(None, None)``.

    The stop is checked first so it wins when one bar touches both levels; a
    gap through the stop fills at the open; a target never beats its limit.
    """
    if bracket.stop is not None and (
        (long and low <= bracket.stop) or (not long and high >= bracket.stop)
    ):
        return (min(bracket.stop, open_) if long else max(bracket.stop, open_)), "stop_loss"
    if bracket.target is not None and (
        (long and high >= bracket.target) or (not long and low <= bracket.target)
    ):
        return bracket.target, "take_profit"
    return None, None


def _stamp(when) -> str:
    return when.isoformat() if hasattr(when, "isoformat") else str(when)


class BracketsMixin:
    """Bracket tracking for :class:`DryRunBroker` (needs its portfolio/data/marks)."""

    def _track_bracket(self, order, qty_before: float, fill_price: float,
                       order_id: str | None = None) -> None:
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
            bar = self._latest_bar(order.symbol)
            self._brackets[order.symbol] = _Bracket(
                stop=order.stop_loss, target=order.take_profit, entry=fill_price,
                entry_bar=None if bar is None else bar.name, entry_id=order_id,
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
        - a target never fills better than its limit, even on a favourable gap;
        - a leg is only tested on a bar **after** the entry bar. A data source
          parked on its newest bar (the web dry-run) would otherwise re-test the
          entry bar every pass and book a phantom exit and re-entry each time.

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
            if bar is None or (bracket.entry_bar is not None
                               and not bar.name > bracket.entry_bar):
                continue
            price, reason = exit_price(bracket, float(bar["high"]), float(bar["low"]),
                                       float(bar["open"]), pos.qty > 0)
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
                              commission=self.commission, timestamp=utcnow(), intent="exit",
                              order_id=f"bracket:{bracket.entry_id}:{_stamp(bar.name)}"))
        return exits
