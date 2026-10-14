"""The advisor: what the engine would trade right now, without trading it.

A :class:`Proposal` is the set of signed share deltas one rebalance pass would
submit. Suggestions (the Today page) and executions (``Engine.rebalance``) are
two consumers of the same proposal, so they cannot disagree.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class ProposalLine:
    symbol: str
    action: str            # "buy" | "sell" | "hold"
    target: int            # -1, 0, +1 after selector gating
    current_qty: float
    desired_qty: float
    order_qty: float       # signed delta, 0 for hold
    price: float
    notional: float        # abs(order_qty) * price
    weight: float | None   # post-overlay target weight when an allocator exists
    reason: str            # one sentence
    #: True when the symbol never reached sizing (no bars, bad price, a failing
    #: signal). The engine never submits a skipped line.
    skipped: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Proposal:
    created_at: datetime
    equity: float
    cash: float
    lines: list[ProposalLine]
    provenance: dict = field(default_factory=dict)
    #: The full post-overlay weight map, kept whole because an allocator may
    #: weight symbols the lines do not carry and the engine records it as is.
    weights: dict[str, float] | None = None

    def to_dict(self) -> dict:
        return {
            "created_at": self.created_at.isoformat(),
            "equity": self.equity,
            "cash": self.cash,
            "lines": [line.to_dict() for line in self.lines],
            "provenance": dict(self.provenance),
        }
