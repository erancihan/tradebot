"""The Settings page's data: the editable part of ``config.yaml``, and saving it.

The page edits the same document a hand-written config file holds
(``config_io.settings_to_dict``), so whatever the phone saves is exactly what
``tradebot run --config`` would read. Broker keys are never part of it: the
page only learns whether the server environment has them. Alert destinations
are masked both ways (``settings_secrets``).

The view carries the file's ``version`` (a hash of its bytes) and a save that
posts one is refused when the file changed since: a hand edit or a second phone
is never overwritten by a page that did not see it.
"""

from __future__ import annotations

import hashlib
import threading
from pathlib import Path
from typing import Any

import yaml

from ...config import AlpacaCredentials, Settings
from ...config_io import EDITABLE_KEYS, editable, settings_to_dict, write_settings
from ...data.alpaca_data import _TIMEFRAME_ALIASES
from ...market.registry import CALENDARS
from . import autopilot_service, settings_secrets
from .settings_validate import InvalidSettings, validate

#: Where a save goes when the server started without a config file.
DEFAULT_CONFIG = "config.yaml"

#: One save at a time, so two saves never interleave their read-merge-write.
#: It does not stop a stale page from overwriting a newer file: the version
#: check inside it does.
_SAVE_LOCK = threading.Lock()


class LiveRefused(PermissionError):
    """The web never sets a mode: live stays behind the file and the latch."""


class SettingsChanged(RuntimeError):
    """The file changed after the page loaded it: reload before saving."""


def file_version(path: Path) -> str:
    """sha256 of the file's bytes, ``""`` when there is no file."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError:
        return ""


def target_path(state) -> Path:
    return Path(state.settings_path or DEFAULT_CONFIG)


def credentials_present() -> bool:
    return AlpacaCredentials.from_env() is not None


def view(app, notice: str | None = None) -> dict:
    """``GET /api/settings``: the editable document plus what frames it."""
    state = app.state
    path = target_path(state)
    doc = editable(_shown_document(state, path))
    flags = settings_secrets.configured(doc["notify"])
    doc["notify"] = settings_secrets.masked(doc["notify"])
    return {
        "settings": doc,
        "mode": state.settings.mode,
        "credentials_present": credentials_present(),
        "config_path": str(path),
        "config_exists": path.exists(),
        "version": file_version(path),
        **flags,
        "choices": {"markets": sorted(CALENDARS), "timeframes": list(_TIMEFRAME_ALIASES)},
        "notice": notice,
    }


def save(app, doc: Any) -> dict:
    """Validate, write ``config.yaml``, reload the server's settings, reset the autopilot."""
    if not isinstance(doc, dict):
        raise InvalidSettings("expected a JSON object of settings")
    mode = doc.get("mode")
    if mode is not None and mode != "paper":
        raise LiveRefused("mode cannot be changed from the web; it stays in the config "
                          "file, and live trading also needs the confirmation latch")
    unknown = sorted(set(doc) - set(EDITABLE_KEYS) - {"mode", "version"})
    if unknown:
        raise InvalidSettings(f"not an editable setting: {', '.join(unknown)}")
    state = app.state
    with _SAVE_LOCK:
        path = target_path(state)
        # No version: a page older than the check, accepted as before.
        seen = doc.get("version")
        if seen is not None and seen != file_version(path):
            raise SettingsChanged(f"{path} changed since this page loaded it; reload "
                                  "the page to see the current settings, then save again")
        full = _current_document(state, path)
        stored_notify = dict(full.get("notify") or {})
        full.update(editable(doc))
        full["notify"] = settings_secrets.restore(full.get("notify"), stored_notify)
        validate(full)
        write_settings(path, full)
        state.settings = Settings.from_yaml(path)
        state.settings_path = str(path)
    stopped = autopilot_service.reset(app)
    notice = f"Saved to {path}."
    if stopped:
        notice += (" The autopilot loop was stopped so it does not trade on the old "
                   "settings: open Autopilot and tap a mode to start it again.")
    return view(app, notice)


def _shown_document(state, path: Path) -> dict:
    """The file's truth when it loads, else what the server runs on."""
    try:
        return _current_document(state, path)
    except InvalidSettings:
        return settings_to_dict(state.settings)


def _current_document(state, path: Path) -> dict:
    """What a save merges into: the file as it is now (keeping hand edits to the
    keys the web leaves alone), or the server's defaults with ``mode: paper``."""
    if path.exists():
        try:
            return settings_to_dict(Settings.from_yaml(path))
        except (OSError, yaml.YAMLError, ValueError, TypeError, KeyError) as exc:
            raise InvalidSettings(f"the existing {path} does not load ({exc}); "
                                  "fix or remove it first") from exc
    doc = settings_to_dict(state.settings)
    doc["mode"] = "paper"
    return doc
