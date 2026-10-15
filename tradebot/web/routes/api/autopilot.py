"""JSON for the Autopilot page: the runner's state and the commands it takes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ....autopilot.links import verify
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


@router.post("/autopilot/batches/{batch_id}/{verb}")
def batch_link(batch_id: int, verb: str, exp: int, sig: str, request: Request):
    """The phone push's Approve all / Skip buttons (signed links, see
    ``tradebot.autopilot.links``). The signature is the only credential, so
    these paths skip the cookie gate. Each link acts once: a replay is a 409."""
    state = request.app.state
    if verb not in ("approve", "reject") or not verify(
            state.link_secret, batch_id, verb, exp, sig):
        raise HTTPException(status_code=403, detail="invalid or expired link")
    if not state.used_links.claim(batch_id, verb, exp, sig):
        raise HTTPException(status_code=409, detail="this link was already used")
    try:
        done = autopilot_service.act_on_batch(request.app, batch_id, verb)
    except autopilot_service.AutopilotUnavailable as exc:
        state.used_links.release(batch_id, verb, sig)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"batch_id": batch_id, ("approved" if verb == "approve" else "rejected"): done}
