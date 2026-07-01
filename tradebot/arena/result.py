"""Result objects: one per contestant, plus the ranked leaderboard."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite, nan

from ..backtest import BacktestResult
from .contestant import Contestant

# Statuses a contestant can finish with.
OK = "ok"
ERROR = "error"
TIMEOUT = "timeout"


@dataclass
class ContestantResult:
    contestant: Contestant
    status: str = OK
    score: float | None = None
    result: BacktestResult | None = None
    error: str | None = None
    duration_s: float = 0.0
    rank: int | None = None

    @property
    def name(self) -> str:
        return self.contestant.name

    @property
    def author(self) -> str:
        return self.contestant.author

    @property
    def kind(self) -> str:
        return self.contestant.kind

    @property
    def ok(self) -> bool:
        return self.status == OK

    def _metric(self, attr: str) -> float:
        return getattr(self.result, attr) if self.result is not None else nan

    @property
    def total_return(self) -> float:
        return self._metric("total_return")

    @property
    def sharpe(self) -> float:
        return self._metric("sharpe")

    @property
    def max_drawdown(self) -> float:
        return self._metric("max_drawdown")

    @property
    def num_trades(self) -> int:
        return self.result.num_trades if self.result is not None else 0


@dataclass
class Leaderboard:
    metric: str
    entries: list[ContestantResult] = field(default_factory=list)

    @classmethod
    def build(cls, metric: str, results: list[ContestantResult]) -> "Leaderboard":
        ok = [r for r in results if r.ok]
        failed = [r for r in results if not r.ok]
        # Rank finishers by score, then total return as a tie-breaker. Treat a
        # non-finite score as the worst possible so it never wins.
        ok.sort(
            key=lambda r: (
                r.score if r.score is not None and isfinite(r.score) else float("-inf"),
                r.total_return if isfinite(r.total_return) else float("-inf"),
            ),
            reverse=True,
        )
        for i, r in enumerate(ok, start=1):
            r.rank = i
        return cls(metric=metric, entries=ok + failed)

    @property
    def winner(self) -> ContestantResult | None:
        return self.entries[0] if self.entries and self.entries[0].ok else None

    def table(self) -> str:
        return render_table(self.metric, self.entries)


def _finite(v) -> bool:
    return v is not None and isfinite(v)


def _pct(v) -> str:
    return f"{v:.2%}" if _finite(v) else "-"


def _num(v) -> str:
    return f"{v:.2f}" if _finite(v) else "-"


def render_table(metric: str, rows) -> str:
    """Render a leaderboard from anything exposing the result attributes.

    Works for live ``ContestantResult`` objects and for rows reconstructed from
    storage, so a saved tournament prints identically to a fresh one.
    """
    header = (
        f"{'#':>2}  {'name':<20} {'author':<12} {'kind':<10} "
        f"{'score':>10} {'return':>9} {'sharpe':>8} {'maxDD':>8} "
        f"{'trades':>6}  status"
    )
    lines = ["", f"Leaderboard (ranked by {metric})", header, "-" * len(header)]
    for r in rows:
        rank = str(r.rank) if r.rank is not None else "-"
        score = f"{r.score:.3f}" if _finite(r.score) else "-"
        if r.ok:
            row = (
                f"{rank:>2}  {r.name:<20} {r.author:<12} {r.kind:<10} "
                f"{score:>10} {_pct(r.total_return):>9} {_num(r.sharpe):>8} "
                f"{_pct(r.max_drawdown):>8} {r.num_trades:>6}  ok"
            )
        else:
            row = (
                f"{rank:>2}  {r.name:<20} {r.author:<12} {r.kind:<10} "
                f"{'-':>10} {'-':>9} {'-':>8} {'-':>8} {'-':>6}  "
                f"{r.status.upper()}: {r.error or ''}"
            )
        lines.append(row)
    lines.append("")
    return "\n".join(lines)
