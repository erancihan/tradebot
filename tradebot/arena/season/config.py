"""Season configuration: the field, the market and the recompute budget."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from ...risk import RiskConfig
from ..scenario import Scenario


@dataclass
class SeasonConfig:
    name: str
    symbols: list[str]
    timeframe: str = "1day"
    metric: str = "sharpe"
    algo_paths: list[str] = field(default_factory=list)
    initial_cash: float = 10_000.0
    max_position_pct: float = 0.95
    slippage_bps: float = 1.0
    isolation: str = "thread"   # season recompute runs every tick; thread is light
    #: Per-contestant wall-clock budget for each tick's recompute. Under
    #: `thread` isolation this is a SOFT limit — the runner marks TIMEOUT but
    #: cannot kill the thread, so an over-budget contestant leaks a busy daemon
    #: thread *every tick* and the season slowly grinds to a halt. That is the
    #: documented hazard behind "keep meta strategies out of long seasons".
    #: Use `isolation="process"` to make it a hard kill.
    time_budget_s: float = 10.0

    @property
    def hardened(self) -> bool:
        """Sandboxing only applies to the process runner (a thread shares the
        interpreter, so it cannot be given its own filesystem or netns)."""
        return self.isolation != "thread"

    def scenario(self) -> Scenario:
        return Scenario(
            name=self.name, symbols=list(self.symbols),
            initial_cash=self.initial_cash, slippage_bps=self.slippage_bps,
            risk=RiskConfig(max_position_pct=self.max_position_pct, max_daily_loss_pct=1.0),
        )

    def to_json(self) -> str:
        return json.dumps({
            "algo_paths": self.algo_paths, "initial_cash": self.initial_cash,
            "max_position_pct": self.max_position_pct, "slippage_bps": self.slippage_bps,
            "isolation": self.isolation, "time_budget_s": self.time_budget_s,
        })
