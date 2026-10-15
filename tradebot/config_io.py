"""``Settings`` back to the YAML shape ``Settings.from_dict`` reads.

The Settings page edits a document, not the dataclass: the document is what
lands in ``config.yaml``, so a save is exactly "what a hand-written file would
say". Secrets never appear here; they live in the environment (``.env``).
"""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

import yaml

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


# --- writing ------------------------------------------------------------------

HEADER = ("# Written by the tradebot Settings page. Comments are not kept here:\n"
          "# config.example.yaml documents every key. Secrets live in .env, never here.\n")

#: Key names that would mean a secret slipped into the document.
_SECRET_KEY = re.compile(r"secret|api_key|password|token", re.IGNORECASE)


def write_settings(path: str | Path, doc: dict[str, Any]) -> None:
    """Write ``doc`` as YAML, atomically: a reader sees the old file or the new.

    The text goes to a temporary file in the same directory and is renamed
    over the target, so a crash mid-write never leaves half a config behind.
    """
    leaked = sorted(_secret_keys(doc))
    if leaked:
        raise ValueError(f"refusing to write secrets to a config file: {', '.join(leaked)}")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = HEADER + yaml.safe_dump(_prune(doc), sort_keys=False, default_flow_style=False)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        if path.exists():       # mkstemp makes 0600; keep the owner's choice
            os.chmod(tmp, path.stat().st_mode & 0o777)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _secret_keys(node: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if _SECRET_KEY.search(str(key)):
                found.add(str(key))
            found |= _secret_keys(value)
    elif isinstance(node, list):
        for item in node:
            found |= _secret_keys(item)
    return found


def _prune(node: Any) -> Any:
    """Drop unset values (None, empty blocks) so the file reads like a hand-written one."""
    if isinstance(node, dict):
        pruned = {k: _prune(v) for k, v in node.items()}
        return {k: v for k, v in pruned.items() if v is not None and v != {} and v != []}
    if isinstance(node, list):
        return [_prune(v) for v in node]
    return node
