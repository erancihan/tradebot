"""Server-rendered full pages."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from ..dependencies import (
    get_arena_repo,
    get_season_repo,
    get_trading_repo,
    templates,
)
from ..repository import ArenaRepository, SeasonRepository, TradingRepository
from ..services import (
    account_service,
    advisor_service,
    autopilot_service,
    consortium_service,
    holdings_service,
    metrics_service,
    settings_service,
    whatif_presets,
)
from ..services.jobs import stack_catalog

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, repo: TradingRepository = Depends(get_trading_repo)):
    equity = repo.equity_series(mode=repo.default_mode(), limit=2000)
    weights = repo.latest_weights()
    universe = repo.latest_universe()
    orders = repo.recent_orders(limit=25)
    context = {
        "metrics": metrics_service.summarize(equity),
        "account": account_service.snapshot(repo),
        "orders": orders,
        "modes": repo.modes(),
        "allocations": {**weights, "universe": universe["symbols"]},
        # Nothing recorded at all -> tell the visitor why, not just empty tables.
        "fresh": not equity and not orders,
        "active": "dashboard",
    }
    return templates.TemplateResponse(request, "pages/dashboard.html", context)


@router.get("/today", response_class=HTMLResponse)
def today_page(request: Request, repo: TradingRepository = Depends(get_trading_repo)):
    """Phone-first: the trades the advisor suggests right now, with reasons."""
    state = request.app.state
    context = {"today": advisor_service.view(repo, state.settings, state.settings_path),
               "holdings": holdings_service.view(state.settings, trading_db=state.trading_db,
                                                 cache_dir=state.cache_dir),
               "active": "today"}
    return templates.TemplateResponse(request, "pages/today.html", context)


@router.get("/autopilot", response_class=HTMLResponse)
def autopilot_page(request: Request):
    """Phone-first: the autopilot's mode, its last and next pass, pending trades."""
    return templates.TemplateResponse(
        request, "pages/autopilot.html",
        {"autopilot": autopilot_service.view(request.app), "active": "autopilot"})


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    """Phone-first: everything config.yaml holds that the owner should choose."""
    response = templates.TemplateResponse(
        request, "pages/settings.html",
        {"view": settings_service.view(request.app), "active": "settings"})
    response.headers["Cache-Control"] = "no-store"     # carries masked alert targets
    return response


@router.get("/run", response_class=HTMLResponse)
def run_page(request: Request):
    return templates.TemplateResponse(request, "pages/run.html", {"active": "run"})


@router.get("/whatif", response_class=HTMLResponse)
def whatif_page(request: Request):
    return templates.TemplateResponse(
        request, "pages/whatif.html",
        {"active": "whatif", "stack": stack_catalog(),
         "presets": whatif_presets.presets(request.app.state.cache_dir)})


@router.get("/seasons", response_class=HTMLResponse)
def seasons_page(request: Request, repo: SeasonRepository = Depends(get_season_repo)):
    seasons = repo.list_seasons()
    sid = seasons[0]["id"] if seasons else None
    return _render_seasons(request, repo, seasons, sid)


@router.get("/seasons/{season_id}", response_class=HTMLResponse)
def season_page(season_id: int, request: Request,
                repo: SeasonRepository = Depends(get_season_repo)):
    return _render_seasons(request, repo, repo.list_seasons(), season_id)


def _render_seasons(request, repo, seasons, season_id):
    info = repo.get_season(season_id) if season_id is not None else None
    standings = repo.latest_standings(season_id) if season_id is not None else []
    return templates.TemplateResponse(
        request, "pages/seasons.html",
        {"active": "seasons", "seasons": seasons, "season": info,
         "standings": standings, "season_id": season_id},
    )


@router.get("/chart", response_class=HTMLResponse)
def chart_page(request: Request, repo: TradingRepository = Depends(get_trading_repo)):
    symbols = repo.symbols()
    return templates.TemplateResponse(
        request, "pages/chart.html",
        {"active": "chart", "symbols": symbols, "modes": repo.modes()},
    )


@router.get("/arena", response_class=HTMLResponse)
def arena(request: Request, repo: ArenaRepository = Depends(get_arena_repo)):
    runs = repo.list_runs()
    latest = runs[0]["id"] if runs else None
    return _render_arena(request, repo, runs, latest)


@router.get("/arena/{run_id}", response_class=HTMLResponse)
def arena_run(
    run_id: int, request: Request, repo: ArenaRepository = Depends(get_arena_repo)
):
    runs = repo.list_runs()
    return _render_arena(request, repo, runs, run_id)


def _render_arena(request, repo, runs, run_id):
    detail = repo.get_run(run_id) if run_id is not None else None
    context = {
        "runs": runs,
        "run": detail["run"] if detail else None,
        "entries": detail["results"] if detail else [],
        "run_id": run_id,
        "active": "arena",
    }
    return templates.TemplateResponse(request, "pages/arena.html", context)


@router.get("/consortium", response_class=HTMLResponse)
def consortium_page(request: Request, voice: str = "equal",
                    repo: TradingRepository = Depends(get_trading_repo)):
    """The advisory panel: what every algorithm would hold right now."""
    panel = consortium_service.panel(repo, voice_name=voice)
    return templates.TemplateResponse(
        request, "pages/consortium.html",
        {"panel": panel, "voice": panel["voice"], "active": "consortium"},
    )
