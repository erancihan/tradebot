"""Voice schemes: how much each member's opinion counts at each bar."""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np
import pandas as pd


class Voice(ABC):
    """How much each member's recommendation counts, bar by bar."""

    #: Bars of member history needed before the scheme means anything.
    required_history: int = 0

    @abstractmethod
    def weights(self, curves: pd.DataFrame) -> pd.DataFrame:
        """Per-bar voice per member, rows summing to 1.

        ``curves`` is bars × members of each member's own equity. Row ``t`` of
        the result must depend only on rows **strictly before** ``t`` — the same
        one-bar discipline every other decision in this codebase obeys.
        """


class EqualVoice(Voice):
    """Every member counts the same.

    The default, and the baseline any adaptive scheme has to beat. Equal
    weighting across a panel is famously hard to improve on, and unlike every
    adaptive alternative it cannot chase noise.
    """

    name = "equal"

    def weights(self, curves: pd.DataFrame) -> pd.DataFrame:
        if curves.empty or not len(curves.columns):
            return curves.copy()
        share = 1.0 / len(curves.columns)
        return pd.DataFrame(share, index=curves.index, columns=curves.columns)


class HedgeVoice(Voice):
    """Exponential weights on each member's own realised P&L.

    ``voice_m ∝ exp(eta · cumulative log return of m, up to the previous bar)``,
    renormalised, then mixed with a uniform floor.

    Two deliberate choices:

    - **Hedge, not "follow the leader".** Exponential weights carry a regret
      bound — over a run it does no worse than the best single member in
      hindsight, up to a log term. Greedily backing the current leader carries
      no such guarantee, and this project has already measured how that class of
      rule behaves: a trailing-return selector beat random in 4 of 8 draws (see
      the canary note in CLAUDE.md). Assume any adaptive scheme is mostly
      chasing noise until it demonstrates otherwise.
    - **A floor.** No member is ever fully silenced, so a member that comes good
      again can recover. Silence is a dimmer, not a door.

    ``eta`` is the learning rate: 0 reproduces :class:`EqualVoice`, large values
    approach winner-take-all. It is a free parameter and therefore a researcher
    degree of freedom — declare it when quoting any result.
    """

    name = "hedge"

    def __init__(self, eta: float = 2.0, floor: float = 0.02) -> None:
        if eta < 0:
            raise ValueError(f"eta must be >= 0, got {eta}")
        if not 0 <= floor < 1:
            raise ValueError(f"floor must be in [0, 1), got {floor}")
        self.eta = float(eta)
        self.floor = float(floor)

    def weights(self, curves: pd.DataFrame) -> pd.DataFrame:
        n = len(curves.columns)
        if curves.empty or not n:
            return curves.copy()
        if self.floor * n >= 1.0:
            raise ValueError(
                f"floor {self.floor} is unsatisfiable for {n} members "
                f"(needs floor < {1.0 / n:.4f})")

        # Cumulative log return per member, lagged one bar: the voice used at
        # bar t may only reflect performance realised strictly before t.
        safe = curves.replace(0.0, np.nan).ffill()
        log_returns = np.log(safe / safe.shift(1))
        score = log_returns.fillna(0.0).cumsum().shift(1).fillna(0.0)

        # Subtract the row max before exponentiating: scores are cumulative and
        # would otherwise overflow on long runs.
        exponent = self.eta * (score.sub(score.max(axis=1), axis=0))
        raw = np.exp(exponent)
        normalised = raw.div(raw.sum(axis=1), axis=0)
        return normalised * (1.0 - self.floor * n) + self.floor


VOICES = {"equal": EqualVoice, "hedge": HedgeVoice}


def build_voice(name: str | None, params: dict | None = None) -> Voice:
    """Instantiate a registered voice scheme (``equal`` when unset)."""
    if not name:
        return EqualVoice()
    try:
        cls = VOICES[name]
    except KeyError:
        raise ValueError(
            f"Unknown voice scheme {name!r}. Available: {sorted(VOICES)}") from None
    return cls(**(params or {}))
