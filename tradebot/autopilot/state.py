"""Autopilot state: the modes, the state snapshot, and its storage round trip.

The state lives in SQLite (``autopilot_state``) rather than in memory so a
restarted process knows what the user last asked for. Only ``running`` is
process-local: it says whether *this* process has a loop going right now.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

Mode = Literal["off", "approve", "auto"]
MODES: tuple[str, ...] = ("off", "approve", "auto")

#: Human labels for the page, in the order the buttons are drawn.
MODE_LABELS = {"off": "Off", "approve": "Approve first", "auto": "Automatic"}


def check_mode(mode: str) -> Mode:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
    return mode  # type: ignore[return-value]


@dataclass(frozen=True)
class AutopilotState:
    mode: Mode
    running: bool
    account: str                      # the engine's mode label: paper | dry_run
    started_at: datetime | None = None
    last_pass_at: datetime | None = None
    next_pass_at: datetime | None = None
    last_error: str | None = None
    pending: int = 0

    def to_dict(self) -> dict:
        def iso(value: datetime | None) -> str | None:
            return value.isoformat() if value else None

        return {
            "mode": self.mode, "mode_label": MODE_LABELS[self.mode],
            "running": self.running, "account": self.account,
            "started_at": iso(self.started_at), "last_pass_at": iso(self.last_pass_at),
            "next_pass_at": iso(self.next_pass_at), "last_error": self.last_error,
            "pending": self.pending,
        }


def _when(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def load_state(storage, scope: str, *, running: bool = False) -> AutopilotState:
    """The stored state for one account scope; a never-touched scope is off."""
    raw = storage.autopilot_values(scope)
    mode = raw.get("mode") or "off"
    return AutopilotState(
        mode=check_mode(mode) if mode in MODES else "off",
        running=running, account=scope,
        started_at=_when(raw.get("started_at")),
        last_pass_at=_when(raw.get("last_pass_at")),
        next_pass_at=_when(raw.get("next_pass_at")),
        last_error=raw.get("last_error"),
        pending=len(storage.pending_lines(scope)),
    )


def store_mode(storage, scope: str, mode: str, now: datetime) -> None:
    """Persist a mode switch; switching on stamps ``started_at`` and clears
    the last error, so a fresh start does not wear the previous run's failure."""
    mode = check_mode(mode)
    values: dict[str, str | None] = {"mode": mode}
    if mode != "off":
        values.update(started_at=now.isoformat(), last_error=None)
    storage.set_autopilot_values(scope, values)
