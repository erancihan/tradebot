"""Dashboard + chart contracts: equity, orders, candles, account, allocations."""

from __future__ import annotations

from pydantic import BaseModel


class EquityPoint(BaseModel):
    ts: str
    equity: float
    cash: float
    mode: str


class EquitySeries(BaseModel):
    mode: str | None = None
    points: list[EquityPoint]


class OrderRow(BaseModel):
    ts: str
    symbol: str
    side: str
    qty: float
    mode: str


class Candle(BaseModel):
    ts: str
    open: float
    high: float
    low: float
    close: float
    volume: float


class CandleSeries(BaseModel):
    symbol: str
    candles: list[Candle]


class PositionView(BaseModel):
    symbol: str
    qty: float
    avg_price: float


class AccountView(BaseModel):
    source: str                       # alpaca | local | none
    equity: float | None = None
    cash: float | None = None
    buying_power: float | None = None
    market_open: bool | None = None
    positions: list[PositionView] = []


class AllocationRow(BaseModel):
    symbol: str
    weight: float


class AllocationsView(BaseModel):
    ts: str | None = None             # when the weights were last recorded
    mode: str | None = None
    weights: list[AllocationRow] = []
    universe: list[str] = []          # last resolved candidate pool (if any)
    universe_ts: str | None = None
