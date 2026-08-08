"""Pydantic response models for the JSON endpoints (the chart data contracts)."""

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


class LeaderboardEntry(BaseModel):
    rank: int | None
    name: str
    author: str = ""
    kind: str = ""
    status: str
    score: float | None = None
    total_return: float | None = None
    sharpe: float | None = None
    max_drawdown: float | None = None
    num_trades: int = 0


class ArenaCurve(BaseModel):
    name: str
    index: list[str]
    equity: list[float]


class ArenaRunDetail(BaseModel):
    id: int
    scenario: str
    metric: str
    entries: list[LeaderboardEntry]
    curves: list[ArenaCurve]


class RunSummary(BaseModel):
    id: int
    ts: str
    scenario: str
    metric: str
    num_contestants: int
    winner: str | None = None


class SeasonSummary(BaseModel):
    id: int
    name: str
    symbols: str
    timeframe: str
    metric: str
    status: str
    updated_at: str


class SeasonStanding(BaseModel):
    rank: int
    name: str
    total_return: float
    score: float | None = None
    equity: float


class SeasonCurve(BaseModel):
    name: str
    steps: list[int]
    total_return: list[float]


class SeasonDetail(BaseModel):
    id: int
    name: str
    metric: str
    latest: list[SeasonStanding]
    curves: list[SeasonCurve]


class EquityCurve(BaseModel):
    index: list[str]
    equity: list[float]


class StrategyParam(BaseModel):
    name: str
    type: str                         # int | float | bool | str
    default: bool | int | float | str


class StrategySpec(BaseModel):
    name: str
    params: list[StrategyParam] = []


class CacheWindow(BaseModel):
    start: str | None = None          # None = unbounded edge in the manifest
    end: str | None = None


class CacheEntry(BaseModel):
    """One cached (symbol, timeframe): what the Run page's real mode can reach."""

    symbol: str
    timeframe: str
    bars: int
    first: str                        # first/last bar actually on disk
    last: str
    coverage: list[CacheWindow] = []  # provider windows the manifest vouches for


class JobRequest(BaseModel):
    kind: str
    strategy: str = "sma_crossover"
    source: str = "synthetic"         # synthetic | real (cached bars only)
    periods: int = 500                # synthetic only
    seed: int = 42                    # synthetic only
    symbol: str | None = None         # real only
    timeframe: str = "1day"           # real only
    start: str | None = None          # real only; date bounds inside coverage
    end: str | None = None
    initial_cash: float = 10_000.0
    # Left untyped on purpose: coercing to float would turn integer params like
    # `fast`/`period` into floats and break window-size / iloc indexing.
    params: dict | None = None


class JobView(BaseModel):
    id: str
    kind: str
    state: str
    summary: dict | None = None
    equity: EquityCurve | None = None
    provenance: dict | None = None    # what data the job ran on
    error: str | None = None


class ConsortiumMember(BaseModel):
    name: str
    voice: float
    total_return: float
    book: dict[str, float]


class ConsortiumPosition(BaseModel):
    symbol: str
    target: int
    weight: float


class ConsortiumView(BaseModel):
    """The advisory panel. `consensus` is the blend; `members` are its inputs."""

    voice: str
    bars: int
    symbols: list[str]
    members: list[ConsortiumMember]
    consensus: list[ConsortiumPosition]
    errors: list[str] = []
