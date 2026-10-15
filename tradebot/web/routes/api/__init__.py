"""JSON endpoints — the data contracts the ECharts components consume.

Split by page; every sub-router mounts under the one ``/api`` prefix so the
URLs the frontend and tests use are unchanged.
"""

from __future__ import annotations

from fastapi import APIRouter

from . import (arena, autopilot, discover, history, jobs, notify, proposal, settings,
               trading, watchlist, whatif)

router = APIRouter(prefix="/api")
router.include_router(trading.router)
router.include_router(arena.router)
router.include_router(jobs.router)
router.include_router(proposal.router)
router.include_router(whatif.router)
router.include_router(autopilot.router)
router.include_router(notify.router)
router.include_router(watchlist.router)
router.include_router(discover.router)
router.include_router(settings.router)
router.include_router(history.router)
