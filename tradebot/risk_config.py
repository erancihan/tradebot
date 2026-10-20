"""The risk limits a ``RiskManager`` enforces, validated on construction.

Split from ``risk.py`` (which re-exports everything here) so the sizing code
and the limits it reads each stay one concern.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskConfig:
    #: Max fraction of equity to allocate to a single symbol's position.
    max_position_pct: float = 0.10
    #: Max fraction of equity deployed across *all* positions at once.
    max_gross_exposure: float = 1.0
    #: Daily-loss breaker: once equity falls this fraction below the session's
    #: starting equity (e.g. 0.03 == a 3% drawdown today), flatten every equity
    #: position and stay out for the rest of that session day (engine/session.py).
    max_daily_loss_pct: float = 0.03
    #: Trade whole shares only (Alpaca supports fractional, but integers are the
    #: safer default and make sizing math obvious).
    allow_fractional: bool = False
    #: No-trade band: skip rebalancing trades smaller than this fraction of
    #: equity (full exits always execute). 0 disables the band. Cuts the drip
    #: of tiny drift trades that eat returns via slippage.
    rebalance_band_pct: float = 0.0
    #: Bracket exits attached to *entries*, as fractions of the entry price
    #: (0.05 == 5% away). None disables that leg. These live here — not on a
    #: strategy — because they are risk limits: strategies still emit only
    #: {-1, 0, +1}. Live-execution concern; the backtester does not model them
    #: (see the bracket note in CLAUDE.md's invariants).
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None

    def __post_init__(self) -> None:
        for name in ("max_position_pct", "max_gross_exposure", "max_daily_loss_pct",
                     "rebalance_band_pct"):
            v = getattr(self, name)
            if not 0 <= v <= 1:
                raise ValueError(f"{name} must be in [0, 1], got {v}")
        for name in ("stop_loss_pct", "take_profit_pct"):
            v = getattr(self, name)
            # Open at 1: a 100% stop on a long (or target on a short) is a 0.0 price.
            if v is not None and not 0 < v < 1:
                raise ValueError(f"{name} must be in (0, 1) when set, got {v}")


#: The product's no-trade band (1% of equity). ``RiskConfig`` itself keeps 0 so
#: backtests, the arena and the research record keep their numbers; the
#: ``Settings`` a person runs default to this, as config.example.yaml says.
PRODUCT_BAND_PCT = 0.01


def product_risk(**overrides) -> RiskConfig:
    """A ``RiskConfig`` with the product's band unless ``overrides`` sets one."""
    return RiskConfig(**{"rebalance_band_pct": PRODUCT_BAND_PCT, **overrides})
