"""Meta strategies: combine a roster of sub-strategies into one signal.

Two classic constructions:

- :class:`FollowTheLeader` — a greedy bandit. Each bar, score every
  sub-strategy by the trailing return *it would have earned* (its own targets,
  one-bar shifted, times the bar returns — the same accounting the backtester
  uses), and emit the current leader's target. When the regime shifts, the
  leaderboard shifts, and the meta follows.
- :class:`EnsembleVote` — no adaptation, just agreement: go long/short only
  when at least ``min_agree`` sub-strategies say so. Disagreement means flat.

Both are pure functions of bars (row ``t`` depends only on bars ``<= t``), so
they obey the same no-look-ahead contract as every other strategy, and both
default to a mixed trend/mean-reversion roster — the point is regime coverage.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .base import Strategy
from .bollinger_reversion import BollingerReversion
from .donchian_breakout import DonchianBreakout
from .macd_trend import MacdTrend
from .sma_crossover import SmaCrossover


def _default_roster() -> list[Strategy]:
    # Two trend-followers + one crossover + one mean-reverter: something for
    # every regime, which is what gives a meta strategy room to adapt.
    return [SmaCrossover(10, 30), DonchianBreakout(20, 10),
            MacdTrend(), BollingerReversion(20, 2.0)]


def _resolve(strategies) -> list[Strategy]:
    """Accept Strategy instances or {name, params} dicts (from YAML config)."""
    if strategies is None:
        return _default_roster()
    resolved: list[Strategy] = []
    for spec in strategies:
        if isinstance(spec, Strategy):
            resolved.append(spec)
        elif isinstance(spec, dict):
            # Imported here to avoid a cycle (registry imports this module).
            from .registry import build_strategy

            resolved.append(build_strategy(spec["name"], spec.get("params")))
        else:
            raise ValueError(f"Expected a Strategy or a {{name, params}} dict, got {spec!r}")
    if not resolved:
        raise ValueError("meta strategy needs at least one sub-strategy")
    return resolved


class FollowTheLeader(Strategy):
    """Greedy bandit: trade whatever sub-strategy is winning lately.

    ``window`` is the trailing evaluation span in bars. Until every score is
    measurable the unmeasured sub-strategies simply don't compete; before any
    are measurable the meta stays flat. Ties go to roster order (determinism).
    """

    name = "follow_leader"

    def __init__(self, window: int = 63, strategies: list[Any] | None = None) -> None:
        if window < 2:
            raise ValueError(f"window must be >= 2, got {window}")
        self.window = window
        self.strategies = _resolve(strategies)

    @property
    def required_history(self) -> int:
        return max(s.required_history for s in self.strategies) + self.window + 1

    def target_positions(self, bars: pd.DataFrame) -> pd.Series:
        self._validate(bars)
        rets = bars["close"].pct_change()
        targets = pd.DataFrame(
            {i: s.target_positions(bars) for i, s in enumerate(self.strategies)}
        )
        # A sub-strategy's per-bar P&L uses the same one-bar shift as real
        # execution: the target decided at t-1 earns bar t's return.
        perf = targets.shift(1).mul(rets, axis=0)
        scores = perf.rolling(self.window, min_periods=self.window).sum()

        score_np = scores.to_numpy()
        target_np = targets.to_numpy()
        out = np.zeros(len(bars), dtype="int64")
        for i in range(len(bars)):
            row = score_np[i]
            if np.all(np.isnan(row)):
                continue                       # nothing measurable yet: flat
            j = int(np.nanargmax(row))         # first max wins -> roster order
            t = target_np[i, j]
            out[i] = 0 if np.isnan(t) else int(t)
        return pd.Series(out, index=bars.index, dtype="int64")


class EnsembleVote(Strategy):
    """Majority vote: act only when the roster agrees.

    Long when at least ``min_agree`` sub-strategies target +1, short when at
    least ``min_agree`` target -1 (long wins the impossible tie), else flat.
    Default ``min_agree`` is a strict majority of the roster.
    """

    name = "ensemble_vote"

    def __init__(self, strategies: list[Any] | None = None, min_agree: int | None = None) -> None:
        self.strategies = _resolve(strategies)
        if min_agree is None:
            min_agree = len(self.strategies) // 2 + 1
        if not 1 <= min_agree <= len(self.strategies):
            raise ValueError(
                f"min_agree must be in [1, {len(self.strategies)}], got {min_agree}"
            )
        self.min_agree = min_agree

    @property
    def required_history(self) -> int:
        return max(s.required_history for s in self.strategies) + 1

    def target_positions(self, bars: pd.DataFrame) -> pd.Series:
        self._validate(bars)
        targets = pd.DataFrame(
            {i: s.target_positions(bars) for i, s in enumerate(self.strategies)}
        )
        long_votes = (targets == 1).sum(axis=1)
        short_votes = (targets == -1).sum(axis=1)
        out = pd.Series(0, index=bars.index, dtype="int64")
        out[short_votes >= self.min_agree] = -1
        out[long_votes >= self.min_agree] = 1      # long precedence, documented
        return out
