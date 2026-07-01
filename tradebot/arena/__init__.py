"""tradebot.arena — load algorithms dynamically and run them in a competition.

Authors write a contestant as a decorated class in a standalone ``.py`` file:

    from tradebot.arena import register, Algo, Action

    @register(name="my_algo", author="me")
    class MyAlgo(Algo):
        def on_bar(self, bar, ctx) -> Action:
            return Action.long() if bar.close > ctx.sma(20) else Action.flat()

…or reuse the vectorised Strategy interface:

    from tradebot.arena import register
    from tradebot.strategies import Strategy

    @register(name="my_strategy")
    class MyStrategy(Strategy):
        def target_positions(self, bars): ...

Then run a tournament:

    tradebot arena run --algos ./algos --scenario scenarios/default.yaml

Phase 1 is an offline, reproducible *batch* tournament; the result/scoring layer
is designed so a live wall-clock league can reuse it later.
"""

from __future__ import annotations

from .api import register, registered
from .contestant import Contestant
from .interfaces import Action, Algo, Bar, Context
from .league import LeagueResult, Standing, StandingsSnapshot, run_league
from .result import ContestantResult, Leaderboard
from .season import (
    ReplaySeasonFeed,
    Season,
    SeasonConfig,
    SeasonStore,
    run_season,
)
from .scenario import Scenario
from .scoring import available as available_metrics
from .store import ArenaStore
from .tournament import TournamentOutcome, run_tournament

__all__ = [
    "register",
    "registered",
    "Algo",
    "Action",
    "Bar",
    "Context",
    "Contestant",
    "Scenario",
    "Leaderboard",
    "ContestantResult",
    "TournamentOutcome",
    "ArenaStore",
    "run_tournament",
    "run_league",
    "LeagueResult",
    "Standing",
    "StandingsSnapshot",
    "Season",
    "SeasonStore",
    "SeasonConfig",
    "ReplaySeasonFeed",
    "run_season",
    "available_metrics",
]
