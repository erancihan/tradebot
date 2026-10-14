"""JSON for the What-if page: submit a plan as a polled job."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ...schemas import WhatIfRequest
from ...services import whatif_presets

router = APIRouter()

VALID_SOURCES = ("real", "synthetic")
MAX_SYMBOLS = 12                     # a phone form, not a universe screen


@router.post("/whatif")
def create_whatif(req: WhatIfRequest, request: Request):
    symbols = [s.strip().upper() for s in req.symbols if s.strip()]
    if not symbols or len(symbols) > MAX_SYMBOLS:
        raise HTTPException(status_code=400,
                            detail=f"give between 1 and {MAX_SYMBOLS} symbols")
    if req.source not in VALID_SOURCES:
        raise HTTPException(status_code=400, detail=f"source must be one of {VALID_SOURCES}")
    if req.initial_cash <= 0 or req.monthly_contribution < 0:
        raise HTTPException(status_code=400,
                            detail="starting cash must be positive, contributions not negative")
    params = req.model_dump()
    params.update(symbols=list(dict.fromkeys(symbols)),
                  cache_dir=request.app.state.cache_dir)
    return {"job_id": request.app.state.jobs.submit("whatif", params)}


@router.get("/whatif/presets")
def presets(request: Request):
    """Named plans that run on this machine as-is (synthetic when nothing is cached)."""
    return whatif_presets.presets(request.app.state.cache_dir)
