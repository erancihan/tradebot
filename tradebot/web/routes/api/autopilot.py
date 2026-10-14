"""JSON for the Autopilot page: the runner's state and the commands it takes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ...schemas import AutopilotCommand, AutopilotView
from ...services import autopilot_service

router = APIRouter()


@router.get("/autopilot", response_model=AutopilotView)
def state(request: Request):
    return autopilot_service.view(request.app)


@router.post("/autopilot", response_model=AutopilotView)
def command(cmd: AutopilotCommand, request: Request):
    given = [k for k in ("mode", "approve", "reject") if getattr(cmd, k) is not None]
    if len(given) != 1:
        raise HTTPException(status_code=400,
                            detail="send exactly one of: mode, approve, reject")
    if cmd.mode is None:
        raise HTTPException(status_code=400, detail="no pending trades to act on")
    return autopilot_service.set_mode(request.app, cmd.mode)
