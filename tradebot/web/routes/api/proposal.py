"""JSON for the Today page: the latest proposal."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ...dependencies import get_trading_repo
from ...repository import TradingRepository
from ...schemas import ProposalEnvelope
from ...services import advisor_service

router = APIRouter()


@router.get("/proposal", response_model=ProposalEnvelope)
def proposal(request: Request, repo: TradingRepository = Depends(get_trading_repo)):
    state = request.app.state
    return advisor_service.view(repo, state.settings, state.settings_path)
