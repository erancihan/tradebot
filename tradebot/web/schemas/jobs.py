"""Run page contracts: strategy catalog, cache inventory, job request/result."""

from __future__ import annotations

from pydantic import BaseModel


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
    benchmark: EquityCurve | None = None  # what-if only: the buy-and-hold curve
    provenance: dict | None = None    # what data the job ran on
    error: str | None = None
