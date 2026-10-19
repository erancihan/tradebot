"""JSON for the dashboard, chart and consortium pages (trading DB reads)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ...dependencies import get_trading_repo
from ...repository import TradingRepository
from ...schemas import (
    AccountView,
    AllocationRow,
    AllocationsView,
    BenchmarkPoint,
    Candle,
    CandleSeries,
    ConsortiumMember,
    ConsortiumPosition,
    ConsortiumView,
    EquityPoint,
    EquitySeries,
    OrderRow,
    PositionView,
)
from ...services import account_service, benchmark_card, consortium_service

router = APIRouter()


@router.get("/equity", response_model=EquitySeries)
def equity(request: Request, mode: str | None = None, limit: int = 2000,
           repo: TradingRepository = Depends(get_trading_repo)):
    """Snapshots oldest first, plus holding the active list over their window
    (none, with a note, when no ``mode`` is given and the rows mix accounts)."""
    rows = repo.equity_series(mode=mode, limit=limit)
    points = [
        EquityPoint(ts=r["ts"], equity=float(r["equity"]),
                    cash=float(r["cash"]), mode=r["mode"])
        for r in rows
    ]
    bench = benchmark_card.for_snapshots(repo, request.app.state.settings,
                                    request.app.state.cache_dir, rows)
    if bench is None:
        return EquitySeries(mode=mode, points=points)
    series = bench["series"]
    return EquitySeries(
        mode=mode, points=points,
        benchmark=None if series is None else [
            BenchmarkPoint(ts=day.isoformat(), value=float(v)) for day, v in series.items()],
        benchmark_symbols=bench["symbols"], benchmark_since=bench["since"],
        benchmark_until=bench["until"], benchmark_source=bench["source"],
        benchmark_note=bench["note"])


@router.get("/orders", response_model=list[OrderRow])
def orders(mode: str | None = None, limit: int = 100,
           repo: TradingRepository = Depends(get_trading_repo)):
    return [
        OrderRow(ts=r["ts"], symbol=r["symbol"], side=r["side"],
                 qty=float(r["qty"]), mode=r["mode"], status=r["status"],
                 price=r.get("price"), filled_qty=r.get("filled_qty"),
                 fill_price=r.get("fill_price"), filled_at=r.get("filled_at"))
        for r in repo.recent_orders(limit=limit, mode=mode)
    ]


@router.get("/account", response_model=AccountView)
def account(repo: TradingRepository = Depends(get_trading_repo)):
    snap = account_service.snapshot(repo)
    return AccountView(
        source=snap["source"], equity=snap.get("equity"), cash=snap.get("cash"),
        buying_power=snap.get("buying_power"), market_open=snap.get("market_open"),
        positions=[PositionView(**p) for p in snap.get("positions", [])],
        note=snap.get("note"),
    )


@router.get("/allocations", response_model=AllocationsView)
def allocations(mode: str | None = None,
                repo: TradingRepository = Depends(get_trading_repo)):
    w = repo.latest_weights(mode=mode)
    u = repo.latest_universe(mode=mode)
    return AllocationsView(
        ts=w["ts"], mode=w["mode"],
        weights=[AllocationRow(symbol=r["symbol"], weight=float(r["weight"]))
                 for r in w["weights"]],
        universe=u["symbols"], universe_ts=u["ts"],
    )


@router.get("/consortium", response_model=ConsortiumView)
def consortium(voice: str = "equal",
               repo: TradingRepository = Depends(get_trading_repo)):
    """What every algorithm would hold right now, plus the blended book."""
    p = consortium_service.panel(repo, voice_name=voice)
    return ConsortiumView(
        voice=p["voice"], bars=p["bars"], symbols=p["symbols"],
        members=[ConsortiumMember(**m) for m in p["members"]],
        consensus=[ConsortiumPosition(**c) for c in p["consensus"]],
        errors=p["errors"],
    )


@router.get("/symbols", response_model=list[str])
def symbols(repo: TradingRepository = Depends(get_trading_repo)):
    return repo.symbols()


@router.get("/bars", response_model=CandleSeries)
def bars(symbol: str, mode: str | None = None, timeframe: str | None = None,
         limit: int = 500, repo: TradingRepository = Depends(get_trading_repo)):
    # Default to a single timeframe rather than none: `timeframe` is part of the
    # bars primary key, so an unfiltered query returns each timestamp once per
    # stored timeframe and the chart renders overlapping duplicate candles.
    if timeframe is None:
        available = repo.timeframes()
        timeframe = available[0] if len(available) == 1 else timeframe
    candles = [
        Candle(ts=r["ts"], open=float(r["open"]), high=float(r["high"]),
               low=float(r["low"]), close=float(r["close"]), volume=float(r["volume"]))
        for r in repo.bars(symbol, mode=mode, timeframe=timeframe, limit=limit)
    ]
    return CandleSeries(symbol=symbol, candles=candles)
