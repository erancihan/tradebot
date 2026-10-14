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
    try:
        if cmd.mode is not None:
            return autopilot_service.set_mode(request.app, cmd.mode)
        if cmd.approve is not None:
            return autopilot_service.approve(request.app, cmd.approve)
        return autopilot_service.reject(request.app, cmd.reject)
    except autopilot_service.AutopilotUnavailable as exc:
        # Not an HTTP error: the page shows the reason (e.g. the pull command
        # for missing bars) beside an unchanged state.
        return autopilot_service.view(request.app, notice=str(exc))
