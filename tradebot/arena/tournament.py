"""Orchestrates a tournament: discover -> run each contestant -> rank."""

from __future__ import annotations

from dataclasses import dataclass

from ..risk import RiskManager
from .loader import LoadError, discover
from .result import Leaderboard
from .runner import Runner, default_runner
from .scenario import Scenario
from .scoring import get_scorer
from .simulation import SimConfig


@dataclass
class TournamentOutcome:
    leaderboard: Leaderboard
    load_errors: list[LoadError]


def run_tournament(
    paths,
    scenario: Scenario | None = None,
    metric: str = "sharpe",
    runner: Runner | None = None,
    time_budget_s: float = 10.0,
    isolation: str = "process",
    cpu_seconds: int | None = None,
    memory_mb: int | None = None,
    frames=None,
    harden: bool = True,
    seccomp: bool = False,
) -> TournamentOutcome:
    """Load contestants from ``paths`` and rank them over ``scenario``.

    By default each contestant runs in an isolated subprocess with a hard
    timeout + CPU/memory limits (``isolation='process'``), which raises if fork
    is unavailable rather than silently weakening isolation. Pass
    ``isolation='thread'`` for the lightweight (soft) in-process runner, or
    ``isolation='auto'`` to fall back to it automatically when fork is missing.

    ``frames`` (a ``{symbol: DataFrame}`` dict) overrides ``scenario.build_frames()``
    — used by the live season to rank over its accumulated bars. The scenario
    still supplies the shared capital / cost / risk model.
    """
    scenario = scenario or Scenario.default()
    scorer = get_scorer(metric)  # validate metric early (raises on typo)
    runner = runner or default_runner(time_budget_s, isolation, cpu_seconds, memory_mb,
                                       harden, seccomp)

    contestants, load_errors = discover(paths)
    if frames is None:
        frames = scenario.build_frames()
    risk = RiskManager(scenario.risk)
    config = SimConfig(
        initial_cash=scenario.initial_cash,
        commission=scenario.commission,
        slippage_bps=scenario.slippage_bps,
    )

    results = [runner.run(c, frames, risk, config, scorer) for c in contestants]
    return TournamentOutcome(
        leaderboard=Leaderboard.build(metric, results),
        load_errors=load_errors,
    )
