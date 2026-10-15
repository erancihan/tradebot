"""JSON for the Settings page: read the editable config document."""

from __future__ import annotations

from fastapi import APIRouter, Request

from ...services import settings_service

router = APIRouter()


@router.get("/settings")
def settings(request: Request) -> dict:
    return settings_service.view(request.app)
