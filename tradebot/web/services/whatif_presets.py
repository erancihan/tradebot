"""Named starting points for the What-if form, built from what is cached.

A preset must run on this machine as-is, so it is built from the local bar
cache. With an empty cache the presets fall back to synthetic symbols and say
so in their names; the job labels the result synthetic as well.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from . import cache_service

#: Familiar index funds go first when cached, so the default reads naturally.
PREFERRED = ("SPY", "QQQ", "IWM", "DIA", "VTI")
MAX_PRESET_SYMBOLS = 6
SYNTHETIC_SYMBOLS = ["SYN_A", "SYN_B", "SYN_C", "SYN_D"]
SYNTHETIC_WINDOW = ("2021-01-04", "2024-12-31")
#: A real preset needs this much calendar overlap across its symbols; a
#: symbol pulled for a different period would leave a window too short to say
#: anything, or none at all, and the preset would fail on first tap.
MIN_SHARED_DAYS = 90


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
    """Up to six cached symbols, familiar ones first, that share a real window."""
    rank = {s: i for i, s in enumerate(PREFERRED)}
    ordered = sorted(entries, key=lambda e: (rank.get(e["symbol"], len(rank)), e["symbol"]))
    chosen: list[dict] = []
    for entry in ordered:
        trial = [*chosen, entry]
        if not chosen or _shared_days(trial) >= MIN_SHARED_DAYS:
            chosen = trial
        if len(chosen) == MAX_PRESET_SYMBOLS:
            break
    return chosen


def _shared_days(entries: list[dict]) -> int:
    start = date.fromisoformat(max(e["first"] for e in entries)[:10])
    end = date.fromisoformat(min(e["last"] for e in entries)[:10])
    return (end - start).days


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
