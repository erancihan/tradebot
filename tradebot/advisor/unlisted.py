"""Held names that are off the list: the list is the mandate.

The autopilot manages exactly the active list (the watchlist, else the config
symbols). A position in anything else, left over after a name was removed or
bought by hand, gets a line that closes it, so nothing sits unmanaged. Every
such line is a full exit, which the no-trade band never holds back.
"""

from __future__ import annotations

import logging
import math

from ..models import SYMBOL_RE
from .types import ProposalLine

log = logging.getLogger("tradebot.advisor")
_IGNORED: set[str] = set()          # non-equity positions already logged once

#: The reason on a closing line, worded for the phone.
REASONS = {"sell": "not on your list: sell to flat",
           "buy": "not on your list: buy to flat"}
NO_PRICE = "not on your list; no price to size it"


def off_list(positions: dict[str, float], symbols) -> dict[str, float]:
    """Non-flat signed equity holdings whose symbol is not on the list.

    Compared upper-cased, so a config's ``spy`` is the broker's ``SPY``. A
    position that is not an equity ticker (``BTCUSD``, an option) is ignored,
    never sized: logged once per process at info.
    """
    listed = {str(s).strip().upper() for s in symbols}
    out: dict[str, float] = {}
    for sym, qty in sorted(positions.items()):
        if str(sym).upper() in listed or abs(float(qty)) <= 1e-9:
            continue
        if not SYMBOL_RE.match(str(sym)):
            if sym not in _IGNORED:
                _IGNORED.add(sym)
                log.info("Ignoring %s: not an equity ticker, so not managed here", sym)
            continue
        out[sym] = float(qty)
    return out


def unlisted_lines(unlisted: dict[str, tuple[float, float | None]] | None,
                   symbols) -> list[ProposalLine]:
    """One closing line per off-list holding (``symbol -> (qty, price)``).

    Without a usable price the line is skipped, never sized on a guess.
    """
    listed = {str(s).strip().upper() for s in symbols}
    lines: list[ProposalLine] = []
    for sym, (qty, price) in sorted((unlisted or {}).items()):
        current = float(qty)
        if sym.upper() in listed or abs(current) <= 1e-9:
            continue
        if price is None or not math.isfinite(price) or price <= 0:
            lines.append(ProposalLine(
                symbol=sym, action="hold", target=0, current_qty=current,
                desired_qty=current, order_qty=0.0, price=0.0, notional=0.0,
                weight=None, reason=NO_PRICE, skipped=True))
            continue
        action = "sell" if current > 0 else "buy"
        lines.append(ProposalLine(
            symbol=sym, action=action, target=0, current_qty=current, desired_qty=0.0,
            order_qty=-current, price=float(price), notional=abs(current) * float(price),
            weight=None, reason=REASONS[action]))
    return lines
