"""Dashboard + chart contracts: equity, orders, candles, account, allocations."""

from __future__ import annotations

from pydantic import BaseModel


class EquityPoint(BaseModel):
    ts: str
    equity: float
    cash: float
    mode: str


class BenchmarkPoint(BaseModel):
    ts: str                           # the session date of a cached daily close
    value: float


class EquitySeries(BaseModel):
    mode: str | None = None
    points: list[EquityPoint]
    # Equal-weight buy and hold of the active list over the snapshots' window
    # (services/benchmark.py); None, with a note, when no daily bars are cached.
    benchmark: list[BenchmarkPoint] | None = None
    benchmark_symbols: list[str] = []
    benchmark_since: str | None = None
    benchmark_until: str | None = None
    benchmark_source: str | None = None   # "cache": never fetched
    benchmark_note: str | None = None


class OrderRow(BaseModel):
    ts: str
    symbol: str
    side: str
    qty: float
    mode: str
    status: str | None = None       # the broker's last word; None = not asked yet
    price: float | None = None      # the price the order was sized at (None: flatten, old row)
    filled_qty: float | None = None
    fill_price: float | None = None
    filled_at: str | None = None


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
