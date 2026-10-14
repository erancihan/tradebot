"""Today page contracts: the latest stored proposal and its provenance."""

from __future__ import annotations

from pydantic import BaseModel


class ProposalLineView(BaseModel):
    id: int
    symbol: str
    action: str                       # buy | sell | hold
    target: int
    current_qty: float
    desired_qty: float
    order_qty: float
    price: float
    notional: float
    weight: float | None = None
    reason: str
    status: str


class ProposalView(BaseModel):
    id: int
    created_at: str
    age_seconds: float
    mode: str
    equity: float
    cash: float
    account_label: str                # "paper (Alpaca)" | "paper (from log)" | ...
    provenance: dict
    lines: list[ProposalLineView] = []


class ProposalEnvelope(BaseModel):
    """What the Today page needs, including how to get started when empty."""

    configured: bool                  # a config file was loaded
    config_hint: str | None = None    # the command that creates one, when not
    symbols: list[str] = []
    proposal: ProposalView | None = None
