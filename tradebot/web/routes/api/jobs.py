"""JSON for the Run page: strategy catalog, cache inventory, browser jobs."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ...schemas import CacheEntry, JobRequest, JobView, StrategySpec
from ...services import cache_service
from ...services.jobs import VALID_KINDS, VALID_SOURCES, stack_specs, strategy_catalog

router = APIRouter()


@router.get("/strategies", response_model=list[StrategySpec])
def strategies():
    """Every registered strategy with the params a form can express."""
    return [StrategySpec(**s) for s in strategy_catalog()]


@router.get("/stack")
def stack() -> dict:
    """Selectors and allocators a form can pick, each with its simple params."""
    return stack_specs()


@router.get("/cache", response_model=list[CacheEntry])
def cache(request: Request):
    """What the local bar cache holds — the reach of the Run page's real mode."""
    return [CacheEntry(**e) for e in cache_service.inventory(request.app.state.cache_dir)]


@router.post("/jobs")
def create_job(req: JobRequest, request: Request):
    if req.kind not in VALID_KINDS:
        raise HTTPException(status_code=400, detail=f"kind must be one of {VALID_KINDS}")
    if req.source not in VALID_SOURCES:
        raise HTTPException(status_code=400,
                            detail=f"source must be one of {VALID_SOURCES}")
    if req.source == "real" and not req.symbol:
        raise HTTPException(status_code=400, detail="real-data jobs need a symbol")
    job_id = request.app.state.jobs.submit(
        req.kind,
        {"strategy": req.strategy, "periods": req.periods, "seed": req.seed,
         "initial_cash": req.initial_cash, "params": req.params or {},
         "source": req.source, "symbol": req.symbol, "timeframe": req.timeframe,
         "start": req.start, "end": req.end,
         "cache_dir": request.app.state.cache_dir},
    )
    return {"job_id": job_id}


@router.get("/jobs/{job_id}", response_model=JobView)
def read_job(job_id: str, request: Request):
    job = request.app.state.jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return JobView(id=job.id, kind=job.kind, state=job.state,
                   summary=job.summary, equity=job.equity, benchmark=job.benchmark,
                   compare=job.compare, provenance=job.provenance, error=job.error)
