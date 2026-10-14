"""The Today page's data: the latest stored proposal, shaped for the phone.

Reads only. Computing a fresh proposal is a job (``jobs/proposal.py``) so the
request returns at once and the page polls.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..repository import TradingRepository

#: How the account strip names where equity and cash came from.
ACCOUNT_LABELS = {
    "alpaca": "Alpaca",
    "log": "from log",
    "initial_cash": "starting cash",
}

CONFIG_HINT = "cp config.example.yaml config.yaml"


def view(repo: TradingRepository, settings, settings_path: str | None) -> dict:
    """Latest proposal for the server's mode, plus how to get started."""
    stored = repo.latest_proposal(mode=settings.mode)
    return {
        "configured": settings_path is not None,
        "config_hint": None if settings_path else CONFIG_HINT,
        "symbols": list(settings.symbols),
        "proposal": _shape(stored) if stored else None,
    }


def _shape(stored: dict) -> dict:
    created = datetime.fromisoformat(stored["created_at"])
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - created).total_seconds()
    source = (stored.get("provenance") or {}).get("account", "")
    label = ACCOUNT_LABELS.get(source, source or "unknown")
    return {
        "id": stored["id"],
        "created_at": created.isoformat(),
        "age_seconds": max(age, 0.0),
        "mode": stored["mode"],
        "equity": stored["equity"],
        "cash": stored["cash"],
        "account_label": f"{stored['mode']} ({label})",
        "provenance": stored.get("provenance") or {},
        "lines": stored["lines"],
    }
