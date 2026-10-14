"""Autopilot: a supervised runner that trades the paper account on a timer.

Modes: ``off``; ``approve`` (a pass stores the proposal as pending trades and
waits for the user); ``auto`` (a pass submits every line). The web server and
``tradebot run --autopilot`` drive the same runner.
"""

from __future__ import annotations

from .state import MODE_LABELS, MODES, AutopilotState, Mode, check_mode, load_state, store_mode

__all__ = ["MODES", "MODE_LABELS", "AutopilotState", "Mode", "check_mode",
           "load_state", "store_mode"]
