"""Read what every member of a panel *would* hold, bar by bar.

One simulation pass per member, not one per bar. Members are causal and
deterministic — the arena requires it and the season already leans on it — so a
single full-frame pass reproduces exactly what a stepped run would have shown,
and the cost stays ``O(members × bars)`` instead of ``O(members × bars²)``.

The recommendation is read from ``simulate``'s ``on_decision`` hook, at the
point where the loop hands `desired` quantities to the RiskManager. That is the
one place all three contestant kinds converge on the same shape, which is why a
cross-sectional ``PortfolioAlgo`` member needs no special handling here: a book
is a book.

A member's book is expressed as **signed fractions of its own equity**, i.e.
what it would hold trading the whole account alone. Sizing a member against a
slice of the capital would be a different object, and the difference matters
whenever position sizes hit a cap — say so wherever panel results are quoted.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from ..risk import RiskConfig, RiskManager
from .adapters import simulation_args
from .simulation import SimConfig, simulate


@dataclass
class Panel:
    """Every member's book over time, plus the curve each one earned."""

    #: member name -> bars × symbols of signed weights (fraction of equity)
    books: dict[str, pd.DataFrame] = field(default_factory=dict)
    #: bars × members of each member's own equity curve
    curves: pd.DataFrame = field(default_factory=pd.DataFrame)
    #: members that raised while being read, with the error text
    failures: dict[str, str] = field(default_factory=dict)

    @property
    def names(self) -> list[str]:
        return list(self.books)

    def latest(self) -> dict[str, dict[str, float]]:
        """Each member's most recent book — what it recommends right now."""
        out: dict[str, dict[str, float]] = {}
        for name, book in self.books.items():
            if not len(book):
                continue
            row = book.iloc[-1]
            out[name] = {s: float(row[s]) for s in book.columns}
        return out


class _BookRecorder:
    """Turns `on_decision` callbacks into a bars × symbols weight frame."""

    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.index: list = []

    def __call__(self, i, ts, targets, desired, equity, prices) -> None:
        self.index.append(ts)
        if equity <= 0:
            self.rows.append({})
            return
        self.rows.append({
            s: (qty * prices[s]) / equity
            for s, qty in desired.items()
            if s in prices and qty
        })

    def frame(self, symbols) -> pd.DataFrame:
        return pd.DataFrame(self.rows, index=pd.Index(self.index)).reindex(
            columns=list(symbols)).fillna(0.0)


def build_panel(
    members,
    frames: dict[str, pd.DataFrame],
    risk: RiskManager | None = None,
    initial_cash: float = 10_000.0,
    slippage_bps: float = 1.0,
    commission: float = 0.0,
) -> Panel:
    """Run every member once and collect the book it would have held.

    A member that raises is recorded in ``failures`` and left out of the blend
    rather than killing the panel — the whole point of a consortium is that one
    bad member is survivable. Failures are never silent: callers surface them.
    """
    # A member's book is read as a fraction of equity, so it must be sized
    # against the *whole* account. The daily-loss breaker is disabled for the
    # same reason the arena disables it: this is a measurement, not a session.
    risk = risk or RiskManager(RiskConfig(max_position_pct=0.95, max_daily_loss_pct=1.0))
    config = SimConfig(initial_cash=initial_cash, slippage_bps=slippage_bps,
                       commission=commission)
    symbols = list(frames)

    panel = Panel()
    curves: dict[str, pd.Series] = {}
    for member in members:
        recorder = _BookRecorder()
        try:
            policy, extra = simulation_args(member)
            result = simulate(policy, frames, risk, config,
                              on_decision=recorder, **extra)
        except Exception as exc:                     # noqa: BLE001 — reported, not raised
            panel.failures[member.name] = f"{type(exc).__name__}: {exc}"
            continue
        panel.books[member.name] = recorder.frame(symbols)
        curves[member.name] = result.equity_curve

    panel.curves = (pd.DataFrame(curves) if curves else pd.DataFrame())
    return panel


def is_consortium(contestant) -> bool:
    """True for contestants that are themselves panels.

    A consortium pointed at ``./algos`` would otherwise load *itself* as a
    member and recurse without end. Marked by an attribute on the factory rather
    than by name matching, so renaming a contestant cannot reintroduce the loop.
    """
    return bool(getattr(contestant.factory, "is_consortium", False))


def eligible_members(contestants) -> list:
    """Members a consortium may include: everything that is not one itself."""
    return [c for c in contestants if not is_consortium(c)]
