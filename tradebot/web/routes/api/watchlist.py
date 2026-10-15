"""JSON for the Today page's watchlist chips."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from ...dependencies import get_trading_repo
from ...repository import TradingRepository
from ...schemas import WatchlistChange, WatchlistView
from ...services import symbols_service

router = APIRouter()


@router.get("/watchlist", response_model=WatchlistView)
def watchlist(request: Request, repo: TradingRepository = Depends(get_trading_repo)):
    return symbols_service.resolve(request.app.state.settings, repo)


@router.post("/watchlist", response_model=WatchlistView)
def change(body: WatchlistChange, request: Request):
    if (body.add is None) == (body.remove is None):
        raise HTTPException(status_code=400, detail="send exactly one of: add, remove")
    state = request.app.state
    try:
        return symbols_service.change(state.settings, state.trading_db,
                                      add=body.add, remove=body.remove)
    except symbols_service.InvalidSymbols as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
