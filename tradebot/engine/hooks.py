"""The engine's small hooks, called back by its per-concern modules.

Split from ``core.py`` so the pass itself (``step``/``propose``) reads on its
own. ``signals`` asks for the lookback and the selector's frames, ``orders``
books bracket exits, and every module emits events through ``_notify``.
Moved verbatim: no behaviour lives here that the pass does not already call.
"""

from __future__ import annotations

import logging

from . import orders, signals

log = logging.getLogger("tradebot.engine")


class EngineHooksMixin:
    """Mixed into ``Engine``; uses its strategy, components, notifier and mode."""

    def _selector_frames(self, fetched: dict[str, object]) -> dict[str, object]:
        return signals.selector_frames(self, fetched)

    def _notify(self, event: dict) -> None:
        """Emit an observability event. A notifier can never break a trade pass."""
        try:
            self.notifier.send({"mode": self.mode, **event})
        except Exception:
            log.exception("Notifier failed for event %s", event.get("type"))

    def _check_brackets(self) -> None:
        orders.check_brackets(self)

    def _lookback_days(self) -> int:
        # Ensure enough history for every history-hungry component (strategy,
        # selector, allocator, overlays) plus headroom for weekends/holidays.
        needed = self.strategy.required_history
        for component in (self.selector, self.allocator, *self.overlays):
            if component is not None:
                needed = max(needed, component.required_history)
        return max(needed * 2, 60)
