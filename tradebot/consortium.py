"""Combine many algorithms into one book, weighting them by voice.

The premise: don't bet on one algorithm. Run a panel of them, read what each
one *would* hold, and blend those books together. A member that loses money is
not thrown out — its voice shrinks, and it can recover. Membership is
permanent; influence is earned.

Three pieces:

- **Recommendation** — what a member would hold if it traded the whole account
  alone: a signed weight per symbol, as a fraction of equity. Produced by
  :mod:`tradebot.arena.panel`, which reads it out of the one place every
  contestant kind converges on.
- **Voice** — how much each member's opinion counts at each bar
  (:class:`EqualVoice`, :class:`HedgeVoice`).
- **Consensus** — the voice-weighted average of the member books.

The consensus is a *convex* combination of valid weight vectors, so it is
itself a valid weight vector — no renormalisation, and no way for the blend to
lever up beyond what its members were already asking for. Its sign gives the
target and its magnitude gives the conviction, which means **disagreement
shrinks a position rather than producing a coin flip**. That property is the
main reason a panel is worth having over a vote.

Sizing is not done here. The consensus is a *proposal*; `RiskManager` remains
the only place weights become share quantities.
"""

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


def consensus(
    books: dict[str, pd.DataFrame], voice: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Blend member books into one. Returns ``(targets, weights)``.

    ``books`` maps member name to a bars × symbols frame of signed weights;
    ``voice`` is bars × members. The blend is
    ``score(s, t) = Σ_m voice_m(t) · book_m(s, t)`` — a convex combination, so
    the result is already a valid weight vector.

    ``targets`` is the sign of that score (staying in {-1, 0, +1}, because
    strategies never size anything) and ``weights`` is its magnitude: full
    agreement gives a full-conviction position, a split panel gives a small one,
    and a perfectly divided panel stands aside.
    """
    if not books:
        raise ValueError("consensus needs at least one member book")

    names = [m for m in books if m in voice.columns]
    if not names:
        raise ValueError("no member has a voice column")

    index = voice.index
    symbols = sorted({s for m in names for s in books[m].columns})
    score = pd.DataFrame(0.0, index=index, columns=symbols)
    for member in names:
        book = books[member].reindex(index=index, columns=symbols).fillna(0.0)
        score = score.add(book.mul(voice[member], axis=0), fill_value=0.0)

    targets = score.apply(np.sign).fillna(0.0).astype(int)
    return targets, score.abs()


class Consortium:
    """A panel of members acting as one contestant.

    Precomputes the whole member panel once in :meth:`prepare` — the hook both
    execution loops call right after alignment — then answers per bar by lookup.
    That is what keeps it linear: re-deriving the panel on every growing window
    would be quadratic, which is the same trap `_TailBounded` exists to avoid
    for meta strategies.

    Precomputing is only legitimate because every member is causal and
    deterministic (the arena requires it, and the season already relies on it to
    re-rank from scratch each tick). The consensus is still consumed with the
    usual one-bar shift by the loop that drives it.

    **What it lags by, and why.** A member's recommendation is read from what it
    *holds* at bar `t`, which it decided at `t-1`. So the consortium acts on
    intentions one bar older than its members' own. That is inherent to
    replicating an observable portfolio rather than reading minds, it is
    strictly conservative, and it is a real cost — do not quote consortium
    results as if it traded in lockstep with its members.
    """

    def __init__(self, members, voice: Voice | None = None,
                 risk=None, initial_cash: float = 10_000.0,
                 slippage_bps: float = 1.0, commission: float = 0.0) -> None:
        self.members = list(members)
        self.voice = voice or EqualVoice()
        self.risk = risk
        self.initial_cash = initial_cash
        self.slippage_bps = slippage_bps
        self.commission = commission
        self.targets: pd.DataFrame | None = None
        self.weights_frame: pd.DataFrame | None = None
        self.panel = None
        self._fingerprint_seen = None

    @property
    def required_history(self) -> int:
        return max([1, self.voice.required_history,
                    *(getattr(m, "required_history", 1) for m in self.members)])

    @staticmethod
    def _fingerprint(aligned: dict[str, pd.DataFrame]):
        """Identifies the frame set cheaply, without hashing every bar."""
        symbols = tuple(sorted(aligned))
        index = next((aligned[s].index for s in symbols if len(aligned[s])), None)
        if index is None or not len(index):
            return (symbols, 0, None, None)
        return (symbols, len(index), index[0], index[-1])

    def prepare(self, aligned: dict[str, pd.DataFrame]) -> None:
        from .arena.panel import build_panel

        # Idempotent for a given frame set. The consortium is its own signal and
        # its own weighting, so it reaches the loop as two objects — the policy
        # wrapper and the allocator — and both are offered the prepare hook.
        # Rebuilding the panel for the second one would silently double the cost
        # of the most expensive object in the system, which is exactly how this
        # first blew its time budget on the factor library: 68s became 137s and
        # every scenario came back TIMEOUT.
        fingerprint = self._fingerprint(aligned)
        if self.panel is not None and fingerprint == self._fingerprint_seen:
            return
        self._fingerprint_seen = fingerprint

        self.panel = build_panel(
            self.members, aligned, risk=self.risk,
            initial_cash=self.initial_cash, slippage_bps=self.slippage_bps,
            commission=self.commission,
        )
        voice = self.voice.weights(self.panel.curves)
        self.targets, self.weights_frame = consensus(self.panel.books, voice)
        self.voice_frame = voice

    # --- consumed by the execution loops ------------------------------------
    def as_policy(self):
        """A symbol-aware Policy — `VectorizedPolicy` drops the symbol name."""
        return _ConsensusPolicy(self)

    def _lookup(self, frame: pd.DataFrame | None, ts, symbol: str, default):
        if frame is None or symbol not in frame.columns or ts not in frame.index:
            return default
        return frame.at[ts, symbol]

    def target_at(self, ts, symbol: str) -> int:
        return int(self._lookup(self.targets, ts, symbol, 0))

    def weight_at(self, ts, symbol: str) -> float:
        return float(self._lookup(self.weights_frame, ts, symbol, 0.0))

    # --- Allocator protocol --------------------------------------------------
    def weights(self, targets: dict[str, int], frames: dict[str, pd.DataFrame]
                ) -> dict[str, float]:
        """Conviction per symbol for the bar being filled.

        ``frames`` are bars *strictly before* the fill bar (both loops slice it
        that way), so its last timestamp is the bar the decision was made on —
        the same row the target came from.
        """
        active = {s: t for s, t in targets.items() if t != 0}
        if not active:
            return {}
        ts = None
        for frame in frames.values():
            if len(frame):
                ts = frame.index[-1]
                break
        if ts is None:
            return {}
        return {s: self.weight_at(ts, s) for s in active}


class _ConsensusPolicy:
    """Adapts a prepared :class:`Consortium` to the arena's Policy protocol."""

    def __init__(self, consortium: Consortium) -> None:
        self._consortium = consortium

    def prepare(self, aligned: dict[str, pd.DataFrame]) -> None:
        self._consortium.prepare(aligned)

    def reset(self) -> None:
        # Stateless between rounds: everything lives in the prepared frames.
        pass

    def decide(self, symbol: str, window: pd.DataFrame, position, equity: float) -> int:
        if not len(window):
            return 0
        return self._consortium.target_at(window.index[-1], symbol)
