"""Where a job's bars come from, and the provenance record that travels with them.

``synthetic`` invents a seeded price path on an artificial calendar (dates are
labels, not the future). ``real`` replays bars from the local cache **only** —
the dashboard never fetches, so it stays credential-free and read-only.
"""

from __future__ import annotations

# Guard rails so a form submission can't ask for something absurd.
MAX_PERIODS = 5000
MIN_REAL_BARS = 30                       # below this a "result" is pure noise
VALID_SOURCES = ("synthetic", "real")


def _periods(params: dict) -> int:
    return max(30, min(int(params.get("periods", 500)), MAX_PERIODS))


def _equity_payload(index, values) -> dict:
    return {
        "index": [ts.isoformat() for ts in index],
        "equity": [float(v) for v in values],
    }


def _pull_hint(symbol: str, timeframe: str, start, end) -> str:
    """The exact pull command; ``symbol`` may be several, space-separated."""
    parts = [f"tradebot data pull --symbols {symbol}", f"--timeframe {timeframe}"]
    if start:
        parts.append(f"--start {start}")
    if end:
        parts.append(f"--end {end}")
    return " ".join(parts)


def _resolve_frame(params: dict) -> tuple:
    """The job's bars + the provenance record that must travel with them.

    ``real`` reads the local cache with ``fetcher=None`` — never the network.
    The refusal message carries the exact pull command because the fix belongs
    in the operator's terminal, not in the dashboard.
    """
    source = str(params.get("source") or "synthetic")
    if source == "synthetic":
        from ....data.synthetic import synthetic_ohlcv

        seed = int(params.get("seed", 42))
        df = synthetic_ohlcv(periods=_periods(params), seed=seed)
        return df, "DEMO", {
            "source": "synthetic", "symbol": "DEMO", "seed": seed,
            "bars": int(len(df)),
            "start": df.index.min().isoformat(), "end": df.index.max().isoformat(),
            "note": "invented prices on an artificial calendar — dates are labels, not the future",
        }

    from ....data.cache import BarCache

    symbol = str(params.get("symbol") or "").upper()
    timeframe = str(params.get("timeframe") or "1day")
    start, end = params.get("start") or None, params.get("end") or None
    cache = BarCache(params.get("cache_dir") or "data/cache")
    try:
        df = cache.get(symbol, timeframe, start=start, end=end, fetcher=None)
    except RuntimeError:
        raise RuntimeError(
            f"no cached bars for {symbol} ({timeframe}) covering that range — the "
            f"dashboard never fetches. Pull once with: "
            f"{_pull_hint(symbol, timeframe, start, end)}"
        ) from None
    if len(df) < MIN_REAL_BARS:
        raise RuntimeError(
            f"only {len(df)} cached bars in that range — fewer than {MIN_REAL_BARS} "
            "is noise, not a result. Widen the range."
        )
    if len(df) > MAX_PERIODS:
        raise RuntimeError(
            f"{len(df)} bars in that range exceeds the {MAX_PERIODS}-bar job limit — "
            "narrow the range (silent truncation would misrepresent the window)."
        )
    return df, symbol, {
        "source": "real", "symbol": symbol, "timeframe": timeframe,
        "bars": int(len(df)),
        "start": df.index.min().isoformat(), "end": df.index.max().isoformat(),
        "note": "cached Alpaca bars — raw/unadjusted prices, simulated fills and costs",
    }
