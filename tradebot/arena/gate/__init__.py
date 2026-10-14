"""The promotion pass gate: is this algorithm ready for paper trading?

One leaderboard on one dataset proves nothing, so promotion is judged over a
*gauntlet* — the same candidate across several scenarios (the regime library),
always against a baseline (default ``buy_and_hold``: the do-nothing allocation
every idea must beat net of costs). The criteria are deliberately relative
where synthetic data makes absolutes meaningless:

1. **Completes everywhere** — an error or timeout in any scenario fails.
2. **Beats the baseline on average** — mean total return across the gauntlet.
3. **At least as robust in most regimes** — ``worst_fold`` >= the baseline's
   in a strict majority of scenarios (a crash fold can't hide).
4. **Drawdown in bounds** — max drawdown never worse than a limit (default
   -35%) in any scenario.

The verdict is advisory, not magic: it comes with the experiment journal's
attempt count for the candidate's family, because a gate passed on the 20th
try means much less than one passed on the 2nd.
"""

from __future__ import annotations

from .evaluate import evaluate_gate
from .measure import selector_activity
from .report import GateCheck, GateReport

__all__ = ["GateCheck", "GateReport", "evaluate_gate", "selector_activity"]
