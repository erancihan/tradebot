"""JSON for the arena and seasons pages."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ...dependencies import get_arena_repo, get_season_repo
from ...repository import ArenaRepository, SeasonRepository
from ...schemas import (
    ArenaCurve,
    ArenaRunDetail,
    LeaderboardEntry,
    RunSummary,
    SeasonCurve,
    SeasonDetail,
    SeasonStanding,
    SeasonSummary,
)

router = APIRouter()


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
