"""The autopilot loop: tick, sleep until the next wake, repeat.

Split from ``runner.py`` next to the other mixins: the loop only sequences
ticks and naps (the injected ``_sleep``), so it runs offline under a fake
clock, and ``background`` runs it on a thread.
"""

from __future__ import annotations

import logging
from datetime import datetime

from . import schedule
from .state import AutopilotState

log = logging.getLogger("tradebot.autopilot")


class LoopMixin:
    """Mixed into ``Autopilot``; uses its stop event, sleep, clock and brief."""

    # --- the loop --------------------------------------------------------
    def run_forever(self, max_ticks: int | None = None) -> int:
        """Tick, sleep until the next pass, repeat; returns the ticks run.
        Ends when the mode is off, on ``stop()``, or after ``max_ticks``."""
        self._running = True
        ticks = 0
        try:
            while (max_ticks is None or ticks < max_ticks) and not self._stop.is_set():
                state = self._safe_tick()
                ticks += 1
                if state is not None and state.mode == "off" and self.brief is None:
                    break
                if max_ticks is None or ticks < max_ticks:
                    self._sleep(schedule.wait_seconds(
                        self.clock(), self._wake_at(state), self.poll_seconds))
        finally:
            self._running = False
        return ticks

    def _wake_at(self, state: AutopilotState | None) -> datetime | None:
        """The earlier of the next pass (when on) and the next brief; None
        (retry after one poll) when the tick itself failed."""
        if state is None:
            return None
        with self._lock:
            times = [self._brief_wake(self.clock())] if self.brief else []
        if state.mode != "off" and state.next_pass_at:
            times.append(state.next_pass_at)
        return min(times) if times else None

    def _safe_tick(self) -> AutopilotState | None:
        """A tick that cannot kill the loop: ``tick`` records pass errors; what
        is left (e.g. the store failing) has nowhere to go but the log."""
        try:
            return self.tick()
        except Exception:  # noqa: BLE001
            log.exception("Autopilot tick failed; retrying after one poll")
            return None
