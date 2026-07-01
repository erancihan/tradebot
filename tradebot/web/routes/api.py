"""JSON endpoints — the data contracts the ECharts components consume."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from ..dependencies import get_arena_repo, get_season_repo, get_trading_repo
from ..repository import ArenaRepository, SeasonRepository, TradingRepository
from ..schemas import (
    AccountView,
    ArenaCurve,
    ArenaRunDetail,
    Candle,
    CandleSeries,
    EquityPoint,
    EquitySeries,
    JobRequest,
    JobView,
    LeaderboardEntry,
    OrderRow,
    PositionView,
    RunSummary,
    SeasonCurve,
    SeasonDetail,
    SeasonStanding,
    SeasonSummary,
)
from ..services import account_service
from ..services.jobs_service import VALID_KINDS

router = APIRouter(prefix="/api")


@router.get("/equity", response_model=EquitySeries)
def equity(mode: str | None = None, limit: int = 2000,
           repo: TradingRepository = Depends(get_trading_repo)):
    rows = repo.equity_series(mode=mode, limit=limit)
    points = [
        EquityPoint(ts=r["ts"], equity=float(r["equity"]),
                    cash=float(r["cash"]), mode=r["mode"])
        for r in rows
    ]
    return EquitySeries(mode=mode, points=points)


@router.get("/orders", response_model=list[OrderRow])
def orders(mode: str | None = None, limit: int = 100,
           repo: TradingRepository = Depends(get_trading_repo)):
    return [
        OrderRow(ts=r["ts"], symbol=r["symbol"], side=r["side"],
                 qty=float(r["qty"]), mode=r["mode"])
        for r in repo.recent_orders(limit=limit, mode=mode)
    ]


@router.get("/account", response_model=AccountView)
def account(repo: TradingRepository = Depends(get_trading_repo)):
    snap = account_service.snapshot(repo)
    return AccountView(
        source=snap["source"], equity=snap.get("equity"), cash=snap.get("cash"),
        buying_power=snap.get("buying_power"), market_open=snap.get("market_open"),
        positions=[PositionView(**p) for p in snap.get("positions", [])],
    )


@router.get("/symbols", response_model=list[str])
def symbols(repo: TradingRepository = Depends(get_trading_repo)):
    return repo.symbols()


@router.get("/bars", response_model=CandleSeries)
def bars(symbol: str, mode: str | None = None, limit: int = 500,
         repo: TradingRepository = Depends(get_trading_repo)):
    candles = [
        Candle(ts=r["ts"], open=float(r["open"]), high=float(r["high"]),
               low=float(r["low"]), close=float(r["close"]), volume=float(r["volume"]))
        for r in repo.bars(symbol, mode=mode, limit=limit)
    ]
    return CandleSeries(symbol=symbol, candles=candles)


@router.get("/arena/runs", response_model=list[RunSummary])
def arena_runs(repo: ArenaRepository = Depends(get_arena_repo)):
    return [
        RunSummary(id=r["id"], ts=r["ts"], scenario=r["scenario"], metric=r["metric"],
                   num_contestants=r["num_contestants"], winner=r.get("winner"))
        for r in repo.list_runs()
    ]


@router.get("/arena/runs/{run_id}", response_model=ArenaRunDetail)
def arena_run(run_id: int, repo: ArenaRepository = Depends(get_arena_repo)):
    detail = repo.get_run(run_id)
    if detail is None:
        return ArenaRunDetail(id=run_id, scenario="", metric="", entries=[], curves=[])

    entries, curves = [], []
    for r in detail["results"]:
        entries.append(LeaderboardEntry(
            rank=r["rank"], name=r["name"], author=r["author"] or "", kind=r["kind"] or "",
            status=r["status"], score=r["score"], total_return=r["total_return"],
            sharpe=r["sharpe"], max_drawdown=r["max_drawdown"], num_trades=r["num_trades"] or 0,
        ))
        eq = ArenaRepository.parse_equity(r["equity_json"])
        if eq:
            curves.append(ArenaCurve(name=r["name"], index=eq["index"], equity=eq["equity"]))

    run = detail["run"]
    return ArenaRunDetail(id=run["id"], scenario=run["scenario"], metric=run["metric"],
                          entries=entries, curves=curves)


@router.get("/seasons", response_model=list[SeasonSummary])
def seasons(repo: SeasonRepository = Depends(get_season_repo)):
    return [SeasonSummary(**s) for s in repo.list_seasons()]


@router.get("/seasons/{season_id}", response_model=SeasonDetail)
def season_detail(season_id: int, repo: SeasonRepository = Depends(get_season_repo)):
    info = repo.get_season(season_id)
    history = repo.standings_history(season_id)
    latest = [SeasonStanding(**s) for s in repo.latest_standings(season_id)]

    # total_return per contestant over the steps of the season, for charting.
    series: dict[str, dict[int, float]] = {}
    for snap in history:
        for s in snap["standings"]:
            series.setdefault(s["name"], {})[snap["step"]] = s["total_return"]
    curves = [
        SeasonCurve(name=name, steps=sorted(points), total_return=[points[s] for s in sorted(points)])
        for name, points in series.items()
    ]
    return SeasonDetail(
        id=season_id, name=info["name"] if info else "", metric=info["metric"] if info else "",
        latest=latest, curves=curves,
    )


@router.post("/jobs")
def create_job(req: JobRequest, request: Request):
    if req.kind not in VALID_KINDS:
        raise HTTPException(status_code=400, detail=f"kind must be one of {VALID_KINDS}")
    job_id = request.app.state.jobs.submit(
        req.kind,
        {"strategy": req.strategy, "periods": req.periods, "seed": req.seed,
         "initial_cash": req.initial_cash, "params": req.params or {}},
    )
    return {"job_id": job_id}


@router.get("/jobs/{job_id}", response_model=JobView)
def read_job(job_id: str, request: Request):
    job = request.app.state.jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return JobView(id=job.id, kind=job.kind, state=job.state,
                   summary=job.summary, equity=job.equity, error=job.error)
