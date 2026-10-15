"""JSON for the Autopilot page's test-alert button."""

from __future__ import annotations

from fastapi import APIRouter, Request

from ...services import notify_service

router = APIRouter()


@router.post("/notify/test")
def send_test(request: Request):
    """Send "tradebot test alert" through the server's configured channels."""
    return notify_service.send_test(request.app.state.settings)
