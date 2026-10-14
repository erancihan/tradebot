"""Seasons page contracts: standings and their history."""

from __future__ import annotations

from pydantic import BaseModel


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
