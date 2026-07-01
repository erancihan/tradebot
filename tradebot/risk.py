"""Risk management: the layer that stands between a signal and an order.

The RiskManager has two jobs:
  1. Position sizing — turn a target regime (+1/0/-1) into a concrete share
     quantity bounded by a fraction of account equity.
  2. Circuit breakers — refuse to keep trading once a daily loss limit is hit.

Keeping this separate from strategies means every strategy inherits the same
guardrails, and the limits are unit-tested independently of any trading logic.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class RiskConfig:
    #: Max fraction of equity to allocate to a single symbol's position.
    max_position_pct: float = 0.10
    #: Max fraction of equity deployed across *all* positions at once.
    max_gross_exposure: float = 1.0
    #: Halt new risk-increasing trades once equity falls this fraction below the
    #: session's starting equity (e.g. 0.03 == stop after a 3% drawdown today).
    max_daily_loss_pct: float = 0.03
    #: Trade whole shares only (Alpaca supports fractional, but integers are the
    #: safer default and make sizing math obvious).
    allow_fractional: bool = False

    def __post_init__(self) -> None:
        for name in ("max_position_pct", "max_gross_exposure", "max_daily_loss_pct"):
            v = getattr(self, name)
            if not 0 <= v <= 1:
                raise ValueError(f"{name} must be in [0, 1], got {v}")


class DailyLossLimitError(RuntimeError):
    """Raised/used to signal the daily loss circuit breaker has tripped."""


@dataclass
class RiskManager:
    config: RiskConfig

    def target_qty(self, target: int, equity: float, price: float) -> float:
        """Desired *signed* share quantity for a target regime.

        target: +1 long, 0 flat, -1 short. Sizing allocates
        ``max_position_pct`` of equity at ``price``.
        """
        if target == 0 or price <= 0 or equity <= 0:
            return 0.0
        budget = equity * self.config.max_position_pct
        raw = budget / price
        qty = raw if self.config.allow_fractional else math.floor(raw)
        return math.copysign(qty, target) if qty > 0 else 0.0

    def clamp_to_exposure(
        self, desired_qty: float, price: float, equity: float, current_gross: float
    ) -> float:
        """Reduce a desired quantity so total gross exposure stays within limit.

        ``current_gross`` is the absolute market value of *other* positions
        already held (excluding the one being adjusted).
        """
        if desired_qty == 0:
            return 0.0
        cap = equity * self.config.max_gross_exposure
        room = cap - current_gross
        if room <= 0:
            return 0.0
        max_qty = room / price
        if not self.config.allow_fractional:
            max_qty = math.floor(max_qty)
        bounded = min(abs(desired_qty), max_qty)
        return math.copysign(bounded, desired_qty) if bounded > 0 else 0.0

    def daily_loss_tripped(self, start_equity: float, current_equity: float) -> bool:
        """True when today's drawdown breaches ``max_daily_loss_pct``."""
        if start_equity <= 0:
            return False
        drawdown = (start_equity - current_equity) / start_equity
        return drawdown >= self.config.max_daily_loss_pct
