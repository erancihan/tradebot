"""JSON for the Today page's Discover card: start a search, read the last one."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ...dependencies import get_trading_repo
from ...repository import TradingRepository
from ...services import discover_service

router = APIRouter()


@router.get("/discover")
def discover(repo: TradingRepository = Depends(get_trading_repo)):
    return discover_service.view(repo)


@router.post("/discover/run")
def run(request: Request):
    """Rank unwatched, unheld names as a polled job; the result is stored."""
    state = request.app.state
    job_id = state.jobs.submit("discover", {
        "settings": state.settings, "trading_db": state.trading_db,
        "cache_dir": state.cache_dir,
    })
    return {"job_id": job_id}
