"""What-if page contracts: the plan a phone form can express."""

from __future__ import annotations

from pydantic import BaseModel


class WhatIfRequest(BaseModel):
    symbols: list[str]
    source: str = "real"              # real (cached bars only) | synthetic
    start: str | None = None          # ISO date; real: inside cache coverage
    end: str | None = None
    initial_cash: float = 10_000.0
    monthly_contribution: float = 0.0
    strategy: str = "buy_and_hold"
    # Param dicts stay untyped on purpose: coercing to float would turn integer
    # params like `fast`/`top_k` into floats and break window and rank logic.
    params: dict | None = None
    allocation: str = "equal"
    allocation_params: dict | None = None
    selector: str | None = None
    selector_params: dict | None = None
    seed: int = 42                    # synthetic only
