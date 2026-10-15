"""Order-side steps of a rebalance pass: submitting deltas and brackets.

Functions take the engine rather than living on it so the engine module stays
an orchestration of the pass; the engine keeps thin methods over these.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from ..models import Order, Side, opens_exposure, utcnow

log = logging.getLogger("tradebot.engine")


@dataclass
class RebalanceAction:
    symbol: str
    target: int
    current_qty: float
    desired_qty: float
    order_qty: float          # signed; 0 means no action
    submitted_id: str | None = None


def check_brackets(engine) -> None:
    """Let a simulating broker fire its resting stops/targets for this bar.

    Duck-typed on purpose: a real broker holds the bracket legs itself and
    exposes no such hook, so this is a no-op live and the `Broker` ABC stays
    as small as it was.
    """
    check = getattr(engine.broker, "check_brackets", None)
    if check is None:
        return
    try:
        fills = check() or []
    except Exception:
        log.exception("Bracket check failed; continuing the pass")
        return
    for fill in fills:
        engine._notify({
            "type": "bracket_exit", "symbol": fill.symbol,
            "qty": fill.qty, "price": fill.price,
            "ts": fill.timestamp.isoformat(),
        })


def current_positions(engine, frames: dict[str, object]) -> dict[str, float]:
    """Signed quantity held per fetched symbol, read from the broker.

    A symbol whose position cannot be read is dropped from ``frames`` (in
    place): sizing it against an unknown holding could double an entry.
    """
    out: dict[str, float] = {}
    for sym in list(frames):
        try:
            out[sym] = float(engine.broker.position(sym).qty)
        except Exception:
            log.exception("Position read failed for %s; skipping it this pass", sym)
            frames.pop(sym)
    return out


def _after_send(action: RebalanceAction, step) -> None:
    """Bookkeeping for an order the broker already has: logged, never raised."""
    try:
        step()
    except Exception:  # noqa: BLE001 - the order is out; a log write must not undo that
        log.exception("%s: order %s was sent but its bookkeeping failed",
                      action.symbol, action.submitted_id)


def exits_first(items: list, line=lambda item: item) -> list:
    """Items whose ``line(item)`` does not open exposure (exits, reductions)
    before entries, each group in its original order (``sorted`` is stable).
    The proposal itself keeps its display order."""
    return sorted(items, key=lambda it: opens_exposure(line(it).current_qty,
                                                       line(it).order_qty))


def submit_line(engine, line, on_submitted=None,
                now: datetime | None = None) -> RebalanceAction:
    """Submit one proposal line's delta. The advisor already applied the band
    and the rounding, so the quantity here is final.

    ``on_submitted`` runs as soon as the broker accepts the order, before any
    bookkeeping. Once the broker has it, nothing after may raise: a failure
    there must not make the caller believe the order was never sent.

    ``now`` is the pass clock (a replay's bar time), so History sorts the
    order beside the batch it came from; live it is the wall clock.
    """
    symbol, target, delta, price = line.symbol, line.target, line.order_qty, line.price
    current = line.current_qty
    action = RebalanceAction(
        symbol=symbol,
        target=target,
        current_qty=current,
        desired_qty=line.desired_qty,
        order_qty=delta,
    )
    if delta == 0:
        log.info("%s: target=%d, holding %.4f shares (no order)", symbol, target, current)
        return action
    # Brackets ride on entries only: a reduction is already an exit, and
    # attaching a stop to it would rest an exit against a position that is
    # on its way out.
    stop = target_price = None
    entry = opens_exposure(current, delta)
    if entry:
        stop, target_price = engine.risk.bracket_prices(delta, price)

    order = Order(symbol=symbol, qty=abs(delta), side=Side.from_delta(delta),
                  stop_loss=stop, take_profit=target_price, created_at=now or utcnow())
    action.submitted_id = engine.broker.submit(order)
    log.info(
        "%s: target=%d, %s %.4f @~%.2f (order %s)%s",
        symbol, target, order.side.value, abs(delta), price, action.submitted_id,
        f" bracket stop={stop:.2f}" if stop else "",
    )
    if on_submitted is not None:
        _after_send(action, on_submitted)
    if engine.storage:
        _after_send(action, lambda: engine.storage.record_order(
            order, action.submitted_id, engine.mode, price=price,
            intent="entry" if entry else "exit"))
    engine._notify({
        "type": "order", "symbol": symbol, "side": order.side.value,
        "qty": abs(delta), "price": price, "target": target,
        "order_id": action.submitted_id,
        "stop_loss": stop, "take_profit": target_price,
    })
    return action
