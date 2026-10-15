"""JSON for the Today page: the latest proposal, its refresh, and the holdings."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ...dependencies import get_trading_repo
from ...repository import TradingRepository
from ...schemas import HoldingsView, ProposalEnvelope
from ...services import advisor_service, holdings_service

router = APIRouter()


@router.get("/proposal", response_model=ProposalEnvelope)
def proposal(request: Request, repo: TradingRepository = Depends(get_trading_repo)):
    state = request.app.state
    return advisor_service.view(repo, state.settings, state.settings_path)


@router.post("/proposal/refresh")
def refresh(request: Request):
    """Compute a fresh proposal on the server as a polled job (ADR 0001)."""
    state = request.app.state
    job_id = state.jobs.submit("proposal", {
        "settings": state.settings, "trading_db": state.trading_db,
        "cache_dir": state.cache_dir,
    })
    return {"job_id": job_id}


@router.get("/holdings", response_model=HoldingsView)
def holdings(request: Request):
    state = request.app.state
    return holdings_service.view(state.settings, trading_db=state.trading_db,
                                 cache_dir=state.cache_dir)
