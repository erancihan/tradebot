"""JSON for the History page: round trips and realised P&L for one account."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from ...dependencies import get_trading_repo
from ...repository import TradingRepository
from ...schemas import TradesView
from ...services import history_service, history_trades

router = APIRouter()


@router.get("/history/trades", response_model=TradesView)
def trades(request: Request, mode: str | None = None,
           repo: TradingRepository = Depends(get_trading_repo)):
    """``mode`` pins the account as the rest of History does; without it, the
    page's default (newest snapshot, else the configured mode)."""
    try:
        mode = history_service.active_mode(repo, request.app.state.settings, mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return history_trades.view(repo, mode)
