"""JSON for the Today page's Discover card: start a search, read the last one."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from ...dependencies import get_trading_repo
from ...repository import TradingRepository
from ...schemas import DiscoverAdd, WatchlistView
from ...services import autopilot_service, discover_service, symbols_service

router = APIRouter()


@router.get("/discover")
def discover(repo: TradingRepository = Depends(get_trading_repo)):
    return discover_service.view(repo)


@router.post("/discover/run")
def run(request: Request):
    """Rank unwatched, unheld names as a polled job; the result is stored.

    Single flight: a second tap while one search runs gets the same job id,
    not a second set of Alpaca calls racing to store a run.
    """
    state = request.app.state
    job_id = state.jobs.submit_once("discover", {
        "settings": state.settings, "trading_db": state.trading_db,
        "cache_dir": state.cache_dir,
    })
    return {"job_id": job_id}


@router.post("/discover/add", response_model=WatchlistView, response_model_exclude_none=True)
def add(body: DiscoverAdd, request: Request):
    """Add a row to the watchlist, keeping the current symbols (seeded when empty)."""
    state = request.app.state
    try:
        view = discover_service.add_to_watchlist(state.settings, state.trading_db,
                                                 body.symbol)
    except symbols_service.InvalidSymbols as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # Same rule as any watchlist edit: a running loop copied the old list.
    if autopilot_service.reset(request.app):
        view["notice"] = ("The autopilot loop was stopped so it does not trade the old "
                          "list: open Autopilot and tap a mode to start it again.")
    return view
