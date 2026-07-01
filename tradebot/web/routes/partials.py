"""HTML fragment endpoints, fetched and swapped client-side by Alpine.

Each returns the *same* component template that the full page includes, so the
markup is defined once and reused for both first paint and live refresh.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from ..dependencies import get_arena_repo, get_trading_repo, templates
from ..repository import ArenaRepository, TradingRepository
from ..services import account_service, metrics_service

router = APIRouter(prefix="/partials")


@router.get("/stats", response_class=HTMLResponse)
def stats(request: Request, repo: TradingRepository = Depends(get_trading_repo)):
    equity = repo.equity_series(limit=2000)
    return templates.TemplateResponse(
        request, "components/stats.html",
        {"metrics": metrics_service.summarize(equity),
         "account": account_service.snapshot(repo)},
    )


@router.get("/orders", response_class=HTMLResponse)
def orders(request: Request, repo: TradingRepository = Depends(get_trading_repo)):
    return templates.TemplateResponse(
        request, "components/orders_table.html",
        {"orders": repo.recent_orders(limit=25)},
    )


@router.get("/positions", response_class=HTMLResponse)
def positions(request: Request, repo: TradingRepository = Depends(get_trading_repo)):
    return templates.TemplateResponse(
        request, "components/positions_table.html",
        {"account": account_service.snapshot(repo)},
    )


@router.get("/leaderboard", response_class=HTMLResponse)
def leaderboard(
    request: Request,
    run_id: int | None = None,
    repo: ArenaRepository = Depends(get_arena_repo),
):
    rid = run_id if run_id is not None else repo.latest_run_id()
    detail = repo.get_run(rid) if rid is not None else None
    return templates.TemplateResponse(
        request, "components/leaderboard_table.html",
        {"entries": detail["results"] if detail else [],
         "run": detail["run"] if detail else None},
    )
