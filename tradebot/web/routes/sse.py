"""Server-Sent Events: a single server→client stream that drives live updates.

The browser opens one `EventSource('/sse/dashboard')`; the server pushes the
account snapshot on an interval (and the event itself acts as a refresh
heartbeat the chart/table components re-fetch on). SSE is the right fit for a
read-only dashboard — plain HTTP, automatic reconnect, no bidirectional channel
to manage. ``limit`` makes the stream finite for tests.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from ..dependencies import get_trading_repo
from ..repository import TradingRepository
from ..services import account_service

router = APIRouter(prefix="/sse")


@router.get("/dashboard")
async def dashboard(request: Request, interval: float = 5.0, limit: int | None = None,
                    repo: TradingRepository = Depends(get_trading_repo)):
    async def events():
        count = 0
        while True:
            if await request.is_disconnected():
                break
            payload = json.dumps(account_service.snapshot(repo))
            yield f"event: account\ndata: {payload}\n\n"
            count += 1
            if limit is not None and count >= limit:
                break
            await asyncio.sleep(max(interval, 0.0))

    return StreamingResponse(
        events(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
