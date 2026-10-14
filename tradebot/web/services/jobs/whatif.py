"""Browser-triggered what-if job (tracer: a fixed stub result)."""

from __future__ import annotations


def _run_whatif(params: dict) -> dict:
    """Stub until the core simulator lands; the shape is the real contract."""
    return {
        "summary": {"final_value": 0.0, "gain": 0.0},
        "equity": {"index": [], "equity": []},
        "benchmark": None,
        "provenance": {"source": "stub", "symbol": ",".join(params.get("symbols") or []),
                       "bars": 0, "start": "", "end": "",
                       "note": "tracer result: nothing was simulated"},
    }
