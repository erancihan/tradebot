"""Held names that are off the list: the list is the mandate.

The autopilot manages exactly the active list (the watchlist, else the config
symbols). A position in anything else, left over after a name was removed or
bought by hand, gets a line that closes it, so nothing sits unmanaged. Every
such line is a full exit, which the no-trade band never holds back.
"""

from __future__ import annotations

import math

from .types import ProposalLine

#: The reason on a closing line, worded for the phone.
REASONS = {"sell": "not on your list: sell to flat",
           "buy": "not on your list: buy to flat"}
NO_PRICE = "not on your list; no price to size it"


def off_list(positions: dict[str, float], symbols) -> dict[str, float]:
    """Non-flat signed holdings whose symbol is not on the list."""
    listed = set(symbols)
    return {s: float(q) for s, q in sorted(positions.items())
            if s not in listed and abs(float(q)) > 1e-9}


def unlisted_lines(unlisted: dict[str, tuple[float, float | None]] | None,
                   symbols) -> list[ProposalLine]:
    """One closing line per off-list holding (``symbol -> (qty, price)``).

    Without a usable price the line is skipped, never sized on a guess.
    """
    listed = set(symbols)
    lines: list[ProposalLine] = []
    for sym, (qty, price) in sorted((unlisted or {}).items()):
        current = float(qty)
        if sym in listed or abs(current) <= 1e-9:
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
