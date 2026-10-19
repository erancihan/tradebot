"""JSON for the Settings page (read and save config.yaml) and the setup card."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response

from ...dependencies import get_trading_repo
from ...repository import TradingRepository
from ...services import settings_service, setup_service
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
    """Body: the editable document plus the ``version`` it was loaded at.
    400 = it would not run, 409 = the file changed since, 422 = a mode change."""
    response.headers.update(NO_STORE)
    try:
        return settings_service.save(request.app, doc)
    except settings_service.LiveRefused as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except settings_service.SettingsChanged as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except InvalidSettings as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/setup")
def setup(request: Request, repo: TradingRepository = Depends(get_trading_repo)) -> dict:
    """What a fresh install still lacks: config, credentials, cached bars."""
    state = request.app.state
    return setup_service.setup_status(state.settings, state.settings_path,
                                      state.cache_dir, repo)
