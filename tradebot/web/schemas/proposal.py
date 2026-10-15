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
    config_hint: str | None = None    # the Settings page link, when not
    symbols: list[str] = []
    symbol_source: str = "config"     # "watchlist" | "config": which list `symbols` is
    proposal: ProposalView | None = None


class WatchlistChange(BaseModel):
    """Exactly one of: symbols to add, symbols to remove."""
    add: list[str] | None = None
    remove: list[str] | None = None


class WatchlistView(BaseModel):
    symbols: list[str]
    source: str                       # "watchlist" | "config"
    notice: str | None = None         # set when an edit stopped the autopilot


class HoldingRow(BaseModel):
    symbol: str
    qty: float
    price: float                      # last cached close (or cost basis, see as_of)
    value: float
    weight: float | None = None       # value / equity
    as_of: str | None = None          # the close's date, or "cost basis"


class HoldingsView(BaseModel):
    source: str                       # "alpaca" | "log"
    equity: float
    rows: list[HoldingRow] = []
    skipped: list[str] = []           # held, but no cached bars to price them
    note: str | None = None
