"""What a server is about to run with: one line for the log and ``--check``.

A service manager shows the owner only the log, so the first line names
everything a misconfigured deploy usually gets wrong: which config and
database were picked up, which hosts the phone may use, and whether the
token and the Alpaca keys reached the process. Secrets are reported by
presence only, never by value.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from ..autopilot import load_state
from ..config import AlpacaCredentials
from ..storage import Storage
from .services import autopilot_service
from .services.settings_validate import validate


def startup_line(app) -> str:
    """One line about the app's config, database, hosts, secrets and autopilot."""
    state = app.state
    with Storage(state.trading_db) as st:
        mode = load_state(st, autopilot_service.scope()).mode
    keys = "present" if AlpacaCredentials.from_env() is not None else "absent"
    return (f"tradebot-web: config={state.settings_path or 'defaults'} "
            f"trading_db={state.trading_db} "
            f"allowed_hosts={','.join(state.allowed_hosts)} "
            f"token={'set' if state.token_required else 'not set'} "
            f"alpaca_keys={keys} autopilot_mode={mode}")


def check_config(settings_path: str | None) -> None:
    """Build every component the config file names, as a Settings save would.

    ``Settings.from_yaml`` alone accepts a misspelled strategy, which would
    only fail once the autopilot builds it, after the service is enabled.
    """
    if settings_path is None:
        return
    raw = yaml.safe_load(Path(settings_path).read_text()) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{settings_path}: not a YAML mapping")
    validate(raw)
