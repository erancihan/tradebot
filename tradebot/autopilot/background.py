"""The autopilot's background thread: start once, stop, and a wakeable nap.

Kept apart from the runner so the loop logic reads on its own; the mixin uses
the runner's ``run_forever`` and its events.
"""

from __future__ import annotations

import threading


class BackgroundMixin:
    """Mixed into ``Autopilot``."""

    def _nap(self, seconds: float) -> None:
        self._wake.wait(seconds)
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
