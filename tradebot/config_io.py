"""``Settings`` back to the YAML shape ``Settings.from_dict`` reads.

The Settings page edits a document, not the dataclass: the document is what
lands in ``config.yaml``, so a save is exactly "what a hand-written file would
say". Secrets never appear here; they live in the environment (``.env``).
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .config import Settings

#: Top-level keys the web may change. Everything else in the file (mode,
#: db_path, costs, universe) is kept as it is.
EDITABLE_KEYS = ("symbols", "timeframe", "poll_seconds", "initial_cash",
                 "strategy", "portfolio", "risk", "notify", "market",
                 "autopilot")


def settings_to_dict(settings: Settings) -> dict[str, Any]:
    """The whole document, in the key order of ``config.example.yaml``."""
    doc: dict[str, Any] = {
        "mode": settings.mode,
        "symbols": list(settings.symbols),
        "timeframe": settings.timeframe,
        "poll_seconds": settings.poll_seconds,
        "market": settings.market,
        "autopilot": {"brief_minutes_before_open": settings.brief_minutes_before_open},
        "initial_cash": settings.initial_cash,
        "commission": settings.commission,
        "slippage_bps": settings.slippage_bps,
        "db_path": settings.db_path,
        "strategy": {"name": settings.strategy_name,
                     "params": dict(settings.strategy_params)},
        "portfolio": _portfolio(settings),
        "risk": asdict(settings.risk),
        "notify": {"webhook_url": settings.notify_webhook_url,
                   "ntfy_topic": settings.notify_ntfy_topic,
                   "ntfy_server": settings.notify_ntfy_server},
    }
    if settings.universe_name is not None:
        doc["universe"] = {"source": settings.universe_name,
                           "params": dict(settings.universe_params)}
    return doc


def _portfolio(settings: Settings) -> dict[str, Any]:
    selector = None
    if settings.selector_name is not None:
        selector = {"name": settings.selector_name,
                    "params": dict(settings.selector_params)}
    return {"selector": selector, "allocation": settings.allocation_name,
            "params": dict(settings.allocation_params),
            "overlays": [dict(o) for o in settings.overlays]}


def editable(doc: dict[str, Any]) -> dict[str, Any]:
    """Only the keys the web may change."""
    return {k: doc[k] for k in EDITABLE_KEYS if k in doc}
