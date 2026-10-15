"""Browser-triggered comparison: every strategy on the what-if plan, ranked."""

from __future__ import annotations

from .catalog import strategy_catalog
from .frames import _equity_payload
from .frames_many import resolve_many
from .whatif import _plan

#: Curves sent to the phone: the best few plus the benchmark. More lines than
#: this on a phone-width chart is a tangle, and the table carries every row.
TOP_CURVES = 5
#: Wall-clock cap for one comparison. Strategies not started by then come back
#: as ``skipped``; on synthetic data the whole registry takes about a second.
BUDGET_S = 120.0


def _curve(result) -> dict:
    curve = result.equity_curve
    return _equity_payload(curve.index, curve.to_numpy())


def _run_whatif_compare(params: dict) -> dict:
    from ....whatif import compare_strategies

    frames, provenance = resolve_many(params)
    names = [s["name"] for s in strategy_catalog()]
    out = compare_strategies(_plan(params, frames), frames, names, budget_s=BUDGET_S)
    rows = out.rows()
    curves = {r["name"]: _curve(out.results[r["name"]]) for r in rows[:TOP_CURVES]}
    curves["benchmark"] = _curve(out.benchmark)
    return {
        "compare": {"rows": rows, "benchmark": out.benchmark_row(), "curves": curves,
                    "errors": out.errors, "skipped": out.skipped,
                    "plan_strategy": str(params.get("strategy") or "buy_and_hold")},
        "provenance": provenance,
    }
