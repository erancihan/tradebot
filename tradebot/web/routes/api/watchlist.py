"""JSON for the Today page's watchlist chips."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from ...dependencies import get_trading_repo
from ...repository import TradingRepository
from ...schemas import WatchlistChange, WatchlistView
from ...services import autopilot_service, symbols_service

router = APIRouter()


@router.get("/watchlist", response_model=WatchlistView, response_model_exclude_none=True)
def watchlist(request: Request, repo: TradingRepository = Depends(get_trading_repo)):
    return symbols_service.resolve(request.app.state.settings, repo)


@router.post("/watchlist", response_model=WatchlistView, response_model_exclude_none=True)
def change(body: WatchlistChange, request: Request):
    if (body.add is None) == (body.remove is None):
        raise HTTPException(status_code=400, detail="send exactly one of: add, remove")
    state = request.app.state
    try:
        view = symbols_service.change(state.settings, state.trading_db,
                                      add=body.add, remove=body.remove)
    except symbols_service.InvalidSymbols as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # A running autopilot copied the old list when it was built: stop it, as
    # a Settings save does, so it never trades symbols the user just removed.
    if autopilot_service.reset(request.app):
        view["notice"] = ("The autopilot loop was stopped so it does not trade the old "
                          "list: open Autopilot and tap a mode to start it again.")
    return view
