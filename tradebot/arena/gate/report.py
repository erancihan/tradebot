"""Gate verdict containers and the human-readable report."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class GateCheck:
    label: str
    passed: bool
    detail: str


@dataclass
class GateReport:
    candidate: str
    baseline: str
    max_drawdown_limit: float
    rows: list[dict] = field(default_factory=list)   # one per scenario
    checks: list[GateCheck] = field(default_factory=list)
    attempts: int | None = None                      # journal count, if known
    family: str | None = None
    notes: list[str] = field(default_factory=list)   # diagnostics, not criteria

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(c.passed for c in self.checks)

    def table(self) -> str:
        head = (f"{'scenario':<18} {'cand ret':>9} {'cand wF':>8} {'cand DD':>8}   "
                f"{'base ret':>9} {'base wF':>8}")
        lines = [
            "",
            f"Pass gate — candidate {self.candidate!r} vs baseline "
            f"{self.baseline!r} over {len(self.rows)} scenario(s)",
            head,
            "-" * len(head),
        ]
        for r in self.rows:
            if r["ok"]:
                lines.append(
                    f"{r['scenario']:<18} {r['cand_return']:>9.2%} {r['cand_worst_fold']:>8.3f} "
                    f"{r['cand_max_drawdown']:>8.2%}   {r['base_return']:>9.2%} "
                    f"{r['base_worst_fold']:>8.3f}"
                )
            else:
                lines.append(f"{r['scenario']:<18} {r['error']}")
        lines.append("")
        for note in self.notes:
            lines.append(f"  ~ {note}")
        if self.notes:
            lines.append("")
        lines.append("criteria:")
        for c in self.checks:
            lines.append(f"  [{'x' if c.passed else ' '}] {c.label:<42} {c.detail}")
        if self.attempts is not None:
            lines.append(
                f"  [!] journal: family {self.family!r} has {self.attempts} "
                "attempt(s) on record — discount the verdict accordingly"
            )
        lines.append("")
        lines.append(f"VERDICT: {'PASS' if self.passed else 'FAIL'}")
        if self.passed:
            lines.append(
                "Next: `tradebot backtest --walk-forward`, then promote to a "
                "replay dry-run and a paper season (see README runbook)."
            )
        lines.append("")
        return "\n".join(lines)
