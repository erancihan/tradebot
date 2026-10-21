"""The autopilot's background thread: start once, stop, and a wakeable nap.

Kept apart from the runner so the loop logic reads on its own; the mixin uses
the runner's ``run_forever`` and its events.
"""

from __future__ import annotations

import threading
from datetime import timedelta

#: The longest single wait on the wake event. ``Event.wait`` counts monotonic
#: time, which stands still while a laptop sleeps: one 13-hour wait set the
#: night before the open would overshoot by every minute the lid was closed.
#: Napping in slices and re-reading the wall clock bounds the overshoot.
NAP_SLICE_SECONDS = 60.0


class BackgroundMixin:
    """Mixed into ``Autopilot``."""

    def _nap(self, seconds: float) -> None:
        """Sleep ``seconds`` by the wall clock (``self.clock``), in slices, so a
        suspended machine wakes the loop within one slice of its deadline. A
        set ``_wake`` (mode switch, stop) ends the nap at once."""
        deadline = self.clock() + timedelta(seconds=seconds)
        while not self._wake.is_set():
            remaining = (deadline - self.clock()).total_seconds()
            if remaining <= 0:
                break
            self._wake.wait(min(remaining, NAP_SLICE_SECONDS))
        self._wake.clear()

    def start(self) -> bool:
        """Run the loop on a background thread, once; returns whether it started.
        Atomic, so two concurrent taps cannot start two loops. Its own lock, not
        ``_lock``: the join below would deadlock on a tick waiting for that."""
        with self._start_lock:
            if self._thread is not None and self._thread.is_alive():
                if not self._stop.is_set():
                    return False
                self._thread.join()         # an "off" is winding down: let it finish
            self._stop.clear()
            self._wake.clear()
            self._running = True
            self._thread = threading.Thread(target=self.run_forever, name="autopilot",
                                            daemon=True)
            self._thread.start()
            return True

    def stop(self, timeout: float | None = 5.0) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout)
