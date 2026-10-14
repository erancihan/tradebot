"""The consortium contestant: a precomputed member panel acting as one book."""

from __future__ import annotations

import pandas as pd

from .consensus import consensus
from .voice import EqualVoice, Voice


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
        from ..arena.panel import build_panel

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
