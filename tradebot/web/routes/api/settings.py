"""JSON for the Settings page: read and save the editable config document."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Request, Response

from ...services import settings_service
from ...services.settings_validate import InvalidSettings

router = APIRouter()

#: The view names where alerts go (masked) and whether keys exist; no proxy or
#: browser cache should keep a copy.
NO_STORE = {"Cache-Control": "no-store"}


@router.get("/settings")
def settings(request: Request, response: Response) -> dict:
    response.headers.update(NO_STORE)
    return settings_service.view(request.app)


@router.post("/settings")
def save(request: Request, response: Response, doc: Any = Body(...)) -> dict:
    """Body: the editable document. 400 = it would not run, 422 = a mode change."""
    response.headers.update(NO_STORE)
    try:
        return settings_service.save(request.app, doc)
    except settings_service.LiveRefused as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except InvalidSettings as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
