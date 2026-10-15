"""History contracts: round trips and realised P&L (``services/history_trades``)."""

from __future__ import annotations

from pydantic import BaseModel


class TradeSummary(BaseModel):
    closed: int
    wins: int
    losses: int
    win_rate: float | None = None
    realised: float
    avg_win: float | None = None
    avg_loss: float | None = None
    best: float | None = None
    worst: float | None = None
    profit_factor: float | None = None    # None without a losing trade


class ClosedTrade(BaseModel):
    symbol: str
    side: str                             # "long" or "short"
    qty: float
    entry_price: float                    # average cost of the entries
    exit_price: float                     # average of the exits
    pnl: float
    pnl_pct: float | None = None
    entry_ts: str | None = None
    exit_ts: str


class OpenTradeRow(BaseModel):
    symbol: str
    side: str
    qty: float
    avg_price: float
    entry_ts: str
    realised: float                       # from partial exits; no unrealised


class TradesProvenance(BaseModel):
    mode: str
    source: str                           # "order log fills"
    orders: int                           # filled orders read


class TradesView(BaseModel):
    summary: TradeSummary
    trades: list[ClosedTrade]             # newest close first
    open: list[OpenTradeRow]
    provenance: TradesProvenance
