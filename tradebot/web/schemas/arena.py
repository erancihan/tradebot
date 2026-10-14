"""Arena page contracts: run summaries, leaderboards, equity curves."""

from __future__ import annotations

from pydantic import BaseModel


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
