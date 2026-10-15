"""HTML fragment endpoints, fetched and swapped client-side by Alpine.

Each returns the *same* component template that the full page includes, so the
markup is defined once and reused for both first paint and live refresh.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from ..dependencies import get_arena_repo, get_trading_repo, templates
from ..repository import ArenaRepository, TradingRepository
from ..services import (
    account_service,
    advisor_service,
    autopilot_service,
    consortium_service,
    history_service,
    holdings_service,
    metrics_service,
)

router = APIRouter(prefix="/partials")


@router.get("/stats", response_class=HTMLResponse)
def stats(request: Request, mode: str | None = None,
          repo: TradingRepository = Depends(get_trading_repo)):
    # Scoped to one mode: an unscoped series splices separate accounts into one
    # curve, so "total return" and "max drawdown" describe a book nobody ran.
    equity = repo.equity_series(mode=mode or repo.default_mode(), limit=2000)
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


@router.get("/allocations", response_class=HTMLResponse)
def allocations(request: Request, repo: TradingRepository = Depends(get_trading_repo)):
    weights = repo.latest_weights()
    universe = repo.latest_universe()
    return templates.TemplateResponse(
        request, "components/allocations_table.html",
        {"allocations": {**weights, "universe": universe["symbols"]}},
    )


@router.get("/proposal", response_class=HTMLResponse)
def proposal(request: Request, repo: TradingRepository = Depends(get_trading_repo)):
    state = request.app.state
    return templates.TemplateResponse(
        request, "components/proposal_list.html",
        {"today": advisor_service.view(repo, state.settings, state.settings_path),
         "holdings": _holdings(state)},
    )


@router.get("/holdings", response_class=HTMLResponse)
def holdings(request: Request):
    return templates.TemplateResponse(
        request, "components/holdings.html", {"holdings": _holdings(request.app.state)})


def _holdings(state) -> dict:
    return holdings_service.view(state.settings, trading_db=state.trading_db,
                                 cache_dir=state.cache_dir)


@router.get("/watchlist", response_class=HTMLResponse)
def watchlist(request: Request, repo: TradingRepository = Depends(get_trading_repo)):
    state = request.app.state
    return templates.TemplateResponse(
        request, "components/watchlist.html",
        {"today": advisor_service.view(repo, state.settings, state.settings_path)},
    )


@router.get("/autopilot", response_class=HTMLResponse)
def autopilot(request: Request):
    return templates.TemplateResponse(
        request, "components/autopilot_panel.html",
        {"autopilot": autopilot_service.view(request.app)},
    )


def _history_mode(request: Request, repo: TradingRepository, mode: str | None) -> str:
    try:
        return history_service.active_mode(repo, request.app.state.settings, mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/history", response_class=HTMLResponse)
def history(request: Request, mode: str | None = None, order_ts: str | None = None,
            order_id: int | None = None, batch_ts: str | None = None,
            batch_id: int | None = None,
            repo: TradingRepository = Depends(get_trading_repo)):
    """One page of History's timeline for ``mode`` (the page's account). The
    next page's URL rides in the ``X-History-Next`` header (empty on the last
    page), so the fragment stays the same markup the page includes."""
    mode = _history_mode(request, repo, mode)
    before_order = history_service.parse_cursor(order_ts, order_id)
    before_batch = history_service.parse_cursor(batch_ts, batch_id)
    page = history_service.events_page(repo, mode, before_order, before_batch)
    first = before_order is None and before_batch is None
    response = templates.TemplateResponse(
        request, "components/history_events.html",
        {"history": {**page, "first_page": first}})
    response.headers["X-History-Next"] = page["next"] or ""
    return response


@router.get("/history/performance", response_class=HTMLResponse)
def history_performance(request: Request, mode: str | None = None,
                        repo: TradingRepository = Depends(get_trading_repo)):
    mode = _history_mode(request, repo, mode)
    return templates.TemplateResponse(
        request, "components/history_performance.html",
        {"history": {"performance": history_service.performance(repo, mode)}})


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


@router.get("/consortium", response_class=HTMLResponse)
def consortium(request: Request, voice: str = "equal",
               repo: TradingRepository = Depends(get_trading_repo)):
    # Not on the auto-refresh poll — see the note in pages/consortium.html.
    return templates.TemplateResponse(
        request, "components/consortium_panel.html",
        {"panel": consortium_service.panel(repo, voice_name=voice)},
    )
