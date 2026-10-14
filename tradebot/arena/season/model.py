"""A resumable season: one tick appends bars and re-ranks the field."""

from __future__ import annotations

import pandas as pd

from ..league import Standing, StandingsSnapshot
from ..tournament import run_tournament
from .config import SeasonConfig
from .store import SeasonStore


def _standings_from_leaderboard(leaderboard) -> list[Standing]:
    out = []
    for e in leaderboard.entries:
        if not e.ok or e.result is None:
            continue
        out.append(Standing(
            rank=e.rank, name=e.name, author=e.author, score=e.score,
            total_return=e.total_return, equity=float(e.result.equity_curve.iloc[-1]),
        ))
    return out


class Season:
    """A resumable league season backed by a :class:`SeasonStore`."""

    def __init__(self, store: SeasonStore, season_id: int, config: SeasonConfig) -> None:
        self.store = store
        self.id = season_id
        self.config = config

    @classmethod
    def create(cls, store: SeasonStore, config: SeasonConfig) -> "Season":
        return cls(store, store.create_season(config), config)

    @classmethod
    def load(cls, store: SeasonStore, season_id: int) -> "Season":
        config = store.get_config(season_id)
        if config is None:
            raise KeyError(f"No season with id {season_id}")
        return cls(store, season_id, config)

    @property
    def step_index(self) -> int:
        return self.store.step_count(self.id)

    def step(self, bars_by_symbol: dict[str, pd.DataFrame]) -> StandingsSnapshot | None:
        """Apply one tick: persist the new bar(s), then re-rank over all history.

        Returns the new standings, or ``None`` while there are too few bars to
        score (the bars are still persisted).
        """
        self.store.append_bars(self.id, bars_by_symbol)
        frames = self.store.load_frames(self.id)
        if not frames or min(len(f) for f in frames.values()) < 2:
            return None

        step = min(len(f) for f in frames.values())
        ts = max(pd.Timestamp(f.index[-1]) for f in frames.values()).isoformat()
        outcome = run_tournament(
            self.config.algo_paths, self.config.scenario(),
            metric=self.config.metric, isolation=self.config.isolation, frames=frames,
            time_budget_s=self.config.time_budget_s,
            # Derived, never hardcoded: a season configured for process
            # isolation must still get its sandbox. Hardcoding False here meant
            # `isolation="process"` silently ran unsandboxed.
            harden=self.config.hardened,
        )
        standings = _standings_from_leaderboard(outcome.leaderboard)
        self.store.record_standings(self.id, step, ts, standings)
        self.store.set_status(self.id, "running")
        return StandingsSnapshot(step=step, total_steps=step, timestamp=ts, standings=standings)


def seed_season(season: "Season", frames: dict[str, pd.DataFrame],
                recompute: bool = True) -> int:
    """Backfill real history into a season so the field starts warmed up.

    A daily season started from zero has no standings worth reading for months:
    `MomentumSelector(lookback=60)` alone is flat for 61 bars, so the first
    quarter of a fresh season measures nothing. Seeding is the fix, and it is
    legitimate — bars are the source of truth, every contestant is causal, and
    the season re-ranks from accumulated bars anyway, so replaying real history
    produces exactly what running live over that period would have.

    What it is *not* is the same claim as live results. The seed window was
    chosen after the fact and everything in it was knowable when the field was
    written, so `seeded_through` records the boundary and every reader is
    expected to keep the two apart.

    Returns the number of bars written. Idempotent: the bars table is keyed on
    ``(season_id, symbol, ts)``, so re-seeding the same window changes nothing.
    """
    if not frames:
        return 0
    season.store.append_bars(season.id, frames)
    written = sum(len(df) for df in frames.values())
    last = max(pd.Timestamp(df.index[-1]) for df in frames.values() if len(df))
    season.store.set_seeded_through(season.id, last.isoformat())

    if recompute:
        # One standings snapshot over the whole seeded history, so the season
        # has a starting table instead of an empty one. Ranking is recomputed
        # from bars on every later tick regardless, so this is a convenience,
        # never a source of truth.
        season.step({})
    return written
