"""Consortium page contract: the advisory panel."""

from __future__ import annotations

from pydantic import BaseModel


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
