"""Autopilot page contracts: the runner's state and the commands it takes."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from .proposal import ProposalLineView


class AutopilotCommand(BaseModel):
    """Exactly one of: a mode switch, lines to approve, lines to reject."""
    mode: Literal["off", "approve", "auto"] | None = None
    approve: list[int] | None = None
    reject: list[int] | None = None


class AutopilotStateView(BaseModel):
    mode: str
    mode_label: str
    running: bool
    account: str                      # paper | dry_run
    started_at: str | None = None
    last_pass_at: str | None = None
    next_pass_at: str | None = None
    last_error: str | None = None
    pending: int


class AutopilotMode(BaseModel):
    key: str
    label: str


class AutopilotView(BaseModel):
    state: AutopilotStateView
    modes: list[AutopilotMode]
    pending: list[ProposalLineView]
