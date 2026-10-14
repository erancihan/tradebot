"""Background job runner for browser-triggered backtests and dry-runs.

Jobs run on a small thread pool so the HTTP request returns immediately with a
job id; the client polls for completion. Each job produces a metrics summary,
an equity curve (for the chart), and a provenance record saying what data it
ran on — so a synthetic result can never masquerade as a real one.

Two data sources. ``synthetic`` invents a seeded price path on an artificial
calendar (dates are labels, not the future). ``real`` replays bars from the
local cache **only** — the dashboard never fetches, so it stays credential-free
and read-only; an uncovered range is answered with the exact ``tradebot data
pull`` command instead of a network call.

State is in-process (a single dict guarded by a lock) — fine for a local,
single-user dashboard; a multi-process deployment would swap this for a shared
queue, which is why the registry is the only thing routes touch.
"""

from __future__ import annotations

from .catalog import strategy_catalog
from .frames import MAX_PERIODS, MIN_REAL_BARS, VALID_SOURCES
from .registry import VALID_KINDS, Job, JobRegistry

__all__ = [
    "MAX_PERIODS", "MIN_REAL_BARS", "VALID_KINDS", "VALID_SOURCES",
    "Job", "JobRegistry", "strategy_catalog",
]
