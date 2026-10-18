"""Execution: a pass's proposal into orders, and the legacy timer loop.

Split from ``core.py`` so the pass (``step``/``propose``) reads on its own.
``_submit_all`` is the tail of ``step``; ``run_forever`` repeats
``rebalance`` for ``tradebot run`` without the autopilot.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime

from ..advisor import Proposal
from . import fills, orders
from .orders import RebalanceAction

log = logging.getLogger("tradebot.engine")


class EngineExecutionMixin:
    """Mixed into ``Engine``; uses its settings, strategy and ``rebalance``."""

    def _submit_all(self, proposal: Proposal, now: datetime
                    ) -> tuple[list[RebalanceAction], list[tuple[str, str]]]:
        """Submit every sized line; returns the actions and the ``(symbol,
        error)`` of each line the broker refused, so a supervisor can say so."""
        actions: list[RebalanceAction] = []
        failed: list[tuple[str, str]] = []
        # Exits first: a swap's sell frees the buying power its buy needs.
        for line in orders.exits_first(proposal.lines):
            if line.skipped:      # never sized: no bars, bad price, failed signal
                continue
            try:
                actions.append(orders.submit_line(self, line, now=now))
            except Exception as exc:  # one bad symbol shouldn't kill the whole pass
                log.exception("Rebalance failed for %s", line.symbol)
                failed.append((line.symbol, orders.error_text(exc)))
        if any(a.submitted_id for a in actions):   # usually filled at once: one look
            fills.reconcile_quietly(self, now=now)
        return actions, failed

    def run_forever(self, max_iterations: int | None = None) -> None:
        log.info(
            "Starting engine: mode=%s symbols=%s strategy=%s every %ss",
            self.mode, self.settings.symbols, self.strategy.name, self.settings.poll_seconds,
        )
        i = 0
        while max_iterations is None or i < max_iterations:
            try:
                self.rebalance()
            except Exception:
                log.exception("Rebalance pass errored; continuing.")
            i += 1
            if max_iterations is not None and i >= max_iterations:
                break
            time.sleep(self.settings.poll_seconds)
