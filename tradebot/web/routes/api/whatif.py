"""JSON for the What-if page: submit a plan as a polled job."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ...schemas import WhatIfRequest
from ...services import symbols_service, whatif_presets

router = APIRouter()

VALID_SOURCES = ("real", "synthetic")
MAX_SYMBOLS = 12                     # a phone form, not a universe screen


def _job_params(req: WhatIfRequest, request: Request) -> dict:
    """A validated plan as job params: shared by a single run and a comparison."""
    if req.source not in VALID_SOURCES:
        raise HTTPException(status_code=400, detail=f"source must be one of {VALID_SOURCES}")
    symbols = list(dict.fromkeys(s.strip().upper() for s in req.symbols if s.strip()))
    if req.source == "real":   # a real symbol names a cache file: never a path
        try:
            symbols = symbols_service.clean(symbols)
        except symbols_service.InvalidSymbols as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not symbols or len(symbols) > MAX_SYMBOLS:
        raise HTTPException(status_code=400,
                            detail=f"give between 1 and {MAX_SYMBOLS} symbols")
    if req.initial_cash <= 0 or req.monthly_contribution < 0:
        raise HTTPException(status_code=400,
                            detail="starting cash must be positive, contributions not negative")
    params = req.model_dump()
    params.update(symbols=symbols,
                  cache_dir=request.app.state.cache_dir)
    return params


@router.post("/whatif")
def create_whatif(req: WhatIfRequest, request: Request):
    return {"job_id": request.app.state.jobs.submit("whatif", _job_params(req, request))}


@router.post("/whatif/compare")
def create_whatif_compare(req: WhatIfRequest, request: Request):
    """The same plan once per strategy (default params), ranked against the benchmark."""
    params = _job_params(req, request)
    return {"job_id": request.app.state.jobs.submit("whatif_compare", params)}


@router.get("/whatif/presets")
def presets(request: Request):
    """Named plans that run on this machine as-is (synthetic when nothing is cached)."""
    return whatif_presets.presets(request.app.state.cache_dir)
