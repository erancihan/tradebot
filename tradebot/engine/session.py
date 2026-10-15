"""The daily-loss breaker: one loss budget per exchange session day.

The anchor is the equity the first pass of a session day sees. Every pass
compares the exchange-local date of ``now`` with the anchor's day and starts
a new session when it changed, so a process that runs for days (``tradebot
run``, a replay) gets a fresh budget each morning instead of measuring its
drawdown since start-up. The autopilot restores a persisted same-day anchor
through ``Engine.reset_session``, which leaves the day to the next pass.

A breach flattens the book: resting orders are cancelled and every open
position is closed at market. The rest of that day's passes stay halted
without trading or re-announcing it.
"""

from __future__ import annotations

import logging
from datetime import date, datetime

from ..market import get_calendar
from ..models import Order, Side, is_equity, utcnow

log = logging.getLogger("tradebot.engine")


def roll_session(engine, now: datetime) -> date:
    """Start a new loss budget when ``now`` is on a later session day."""
    tz = get_calendar(getattr(engine.settings, "market", "us_equities")).timezone
    day = now.astimezone(tz).date()
    if engine._session_day is not None and day != engine._session_day:
        engine._session_start_equity = None
    engine._session_day = day
    return day


def halt_on_daily_loss(engine, equity: float, day: date,
                       now: datetime | None = None) -> bool:
    """Circuit breaker: flatten and stop trading once today's drawdown is too deep."""
    if engine._halted_day == day:
        return True                  # already flat for this session: stay out quietly
    if not engine.risk.daily_loss_tripped(engine._session_start_equity, equity):
        return False
    log.warning("Daily loss limit hit (start=%.2f now=%.2f). Flattening and halting.",
                engine._session_start_equity, equity)
    engine._halted_day = day
    closed = flatten(engine, now)
    engine._notify({
        "type": "halt", "reason": "daily_loss",
        "start_equity": engine._session_start_equity, "equity": equity,
        "limit_pct": engine.risk.config.max_daily_loss_pct, "flattened": closed,
    })
    return True


def flatten(engine, now: datetime | None = None) -> list[str]:
    """Cancel resting orders and close every open equity position at market.
    A crypto or option position in the account is a hand trade: never sold.

    One symbol failing never stops the others from closing; each close is
    logged and recorded like any other order.
    """
    try:
        engine.broker.cancel_all()
    except Exception:  # noqa: BLE001 - closing positions matters more
        log.exception("Cancelling resting orders failed; still flattening")
    try:
        held = engine.broker.positions()
    except Exception:  # noqa: BLE001
        log.exception("Could not read positions to flatten them")
        return []
    closed: list[str] = []
    for symbol, pos in held.items():
        qty = float(pos.qty)
        if qty == 0 or not is_equity(pos):
            continue
        order = Order(symbol=symbol, qty=abs(qty), side=Side.from_delta(-qty),
                      created_at=now or utcnow())
        try:
            order_id = engine.broker.submit(order)
        except Exception:  # noqa: BLE001
            log.exception("%s: closing %.4f shares failed", symbol, qty)
            continue
        log.warning("%s: flattened %.4f shares (order %s)", symbol, qty, order_id)
        closed.append(symbol)
        if engine.storage:
            try:
                engine.storage.record_order(order, order_id, engine.mode)
            except Exception:  # noqa: BLE001 - the order is out; never undo that
                log.exception("%s: close %s sent but not recorded", symbol, order_id)
    return closed
