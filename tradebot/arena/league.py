"""Arena league: run the field over a season and watch the standings evolve.

A *tournament* gives one final ranking. A *league* additionally exposes how the
standings move over the course of the season — the same data each contestant
would have seen tick-by-tick in a live run, sampled at N snapshots.

It reuses ``run_tournament`` to produce each contestant's full equity curve
(each contestant is look-ahead-safe, so its equity at time *t* depends only on
data ≤ *t*). Standings at a snapshot are then the field ranked by the chosen
metric computed on every curve **truncated to that point** — which is exactly
what a true stepped live run would have shown at that moment. Optional ``pace_s``
sleeps between snapshots so you can watch the season unfold.

(The *only* thing this doesn't do versus a real-time league is stream live data
over actual wall-clock days; swapping the data feed + adding persistence is the
next layer, and it would reuse this standings/result structure unchanged.)
"""

from __future__ import annotations

import time as _time
from dataclasses import dataclass, field
from math import inf, isfinite

from ..backtest import BacktestResult
from .result import ContestantResult, Leaderboard
from .scenario import Scenario
from .scoring import Scorer, get_scorer
from .tournament import run_tournament


@dataclass(frozen=True)
class Standing:
    rank: int
    name: str
    author: str
    score: float | None
    total_return: float
    equity: float


@dataclass(frozen=True)
class StandingsSnapshot:
    step: int
    total_steps: int
    timestamp: str          # ISO timestamp of the last bar included
    standings: list[Standing]


@dataclass
class LeagueResult:
    metric: str
    snapshots: list[StandingsSnapshot]
    final: Leaderboard                       # full final ranking (incl. failures)
    load_errors: list = field(default_factory=list)


def _rank_key(score: float | None, total_return: float) -> tuple[float, float]:
    # Mirror Leaderboard.build: non-finite sorts worst.
    s = score if score is not None and isfinite(score) else -inf
    tr = total_return if isfinite(total_return) else -inf
    return (s, tr)


def _standings_at(ok_results: list[ContestantResult], cutoff: int, scorer: Scorer) -> list[Standing]:
    scored = []
    for r in ok_results:
        curve = r.result.equity_curve.iloc[:cutoff]
        if len(curve) < 1:
            continue
        # Score the season-to-date. Metrics are equity-curve based, so empty
        # trades are fine here (win_rate/num_trades aren't used by scorers).
        partial = BacktestResult(
            equity_curve=curve, trades=[],
            initial_cash=r.result.initial_cash,
            periods_per_year=r.result.periods_per_year,
        )
        scored.append((r, partial, scorer(partial)))

    scored.sort(key=lambda t: _rank_key(t[2], t[1].total_return), reverse=True)
    return [
        Standing(rank=i, name=r.name, author=r.author,
                 score=score if isfinite(score) else None,
                 total_return=partial.total_return,
                 equity=float(partial.equity_curve.iloc[-1]))
        for i, (r, partial, score) in enumerate(scored, start=1)
    ]


def _cutoffs(length: int, snapshots: int) -> list[int]:
    if length < 2:
        return [length] if length else []
    n = max(1, min(snapshots, length - 1))
    points = sorted({max(1, round(length * k / n)) for k in range(1, n + 1)})
    points[-1] = length                      # final snapshot always includes all bars
    return points


def run_league(
    paths,
    scenario: Scenario | None = None,
    metric: str = "sharpe",
    snapshots: int = 10,
    runner=None,
    time_budget_s: float = 10.0,
    isolation: str = "process",
    cpu_seconds: int | None = None,
    memory_mb: int | None = None,
    pace_s: float = 0.0,
    on_snapshot=None,
    harden: bool = True,
    seccomp: bool = False,
) -> LeagueResult:
    """Run a league and return its evolving standings + final ranking.

    ``on_snapshot(snapshot)`` is called as each snapshot is computed (for live
    display); ``pace_s`` sleeps between snapshots to simulate a live season.
    """
    outcome = run_tournament(paths, scenario, metric, runner, time_budget_s,
                             isolation, cpu_seconds, memory_mb,
                             harden=harden, seccomp=seccomp)
    scorer = get_scorer(metric)
    ok = [e for e in outcome.leaderboard.entries if e.ok and e.result is not None]

    snaps: list[StandingsSnapshot] = []
    if ok:
        index = ok[0].result.equity_curve.index
        cutoffs = _cutoffs(len(index), snapshots)
        total = len(cutoffs)
        for step, cutoff in enumerate(cutoffs, start=1):
            snap = StandingsSnapshot(
                step=step, total_steps=total,
                timestamp=index[cutoff - 1].isoformat(),
                standings=_standings_at(ok, cutoff, scorer),
            )
            snaps.append(snap)
            if on_snapshot is not None:
                on_snapshot(snap)
            if pace_s and step < total:
                _time.sleep(pace_s)

    return LeagueResult(metric=metric, snapshots=snaps,
                        final=outcome.leaderboard, load_errors=outcome.load_errors)
