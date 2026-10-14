"""Named starting points for the What-if form, built from what is cached.

A preset must run on this machine as-is, so it is built from the local bar
cache. With an empty cache the presets fall back to synthetic symbols and say
so in their names; the job labels the result synthetic as well.
"""

from __future__ import annotations

from pathlib import Path

from . import cache_service

#: Familiar index funds go first when cached, so the default reads naturally.
PREFERRED = ("SPY", "QQQ", "IWM", "DIA", "VTI")
MAX_PRESET_SYMBOLS = 6
SYNTHETIC_SYMBOLS = ["SYN_A", "SYN_B", "SYN_C", "SYN_D"]
SYNTHETIC_WINDOW = ("2021-01-04", "2024-12-31")


def _request(symbols: list[str], source: str, start: str | None, end: str | None,
             monthly: float, **plan) -> dict:
    return {"symbols": symbols, "source": source, "start": start, "end": end,
            "initial_cash": 10_000.0, "monthly_contribution": monthly,
            "strategy": plan.get("strategy", "buy_and_hold"),
            "params": plan.get("params", {}),
            "allocation": "equal",
            "selector": plan.get("selector"),
            "selector_params": plan.get("selector_params", {})}


def _build(symbols: list[str], source: str, start, end, label: str) -> list[dict]:
    names = " ".join(symbols)
    out = [
        {"name": f"{names}, 200 a month{label}",
         "description": "Equal parts of each, plus 200 at the start of every month.",
         "request": _request(symbols, source, start, end, 200.0)},
        {"name": f"All in {symbols[0]}, one lump sum{label}",
         "description": f"10,000 into {symbols[0]} on day one, nothing added.",
         "request": _request(symbols[:1], source, start, end, 0.0)},
        {"name": f"Trend following on {names}{label}",
         "description": "Hold a name only while its fast average is above its slow one.",
         "request": _request(symbols, source, start, end, 200.0, strategy="sma_crossover")},
    ]
    if len(symbols) >= 3:
        out.append({
            "name": f"Momentum: best 2 of {len(symbols)}{label}",
            "description": "Hold the two strongest names over the last six months.",
            "request": _request(symbols, source, start, end, 200.0, selector="momentum",
                                selector_params={"lookback": 126, "skip": 21, "top_k": 2}),
        })
    return out


def _pick(entries: list[dict]) -> list[dict]:
    rank = {s: i for i, s in enumerate(PREFERRED)}
    ordered = sorted(entries, key=lambda e: (rank.get(e["symbol"], len(rank)), e["symbol"]))
    return ordered[:MAX_PRESET_SYMBOLS]


def presets(cache_dir: str | Path) -> list[dict]:
    """Three to four presets; cached daily bars when there are any."""
    entries = [e for e in cache_service.inventory(cache_dir) if e["timeframe"] == "1day"]
    if not entries:
        start, end = SYNTHETIC_WINDOW
        return _build(SYNTHETIC_SYMBOLS, "synthetic", start, end, " (synthetic)")
    chosen = _pick(entries)
    # The window every chosen symbol shares, open-ended at the cache's edge.
    start = max(e["first"] for e in chosen)[:10]
    return _build([e["symbol"] for e in chosen], "real", start, None, "")
