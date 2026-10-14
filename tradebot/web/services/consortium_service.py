"""The advisory panel: what every algorithm would hold right now, side by side.

Read-only and advisory. Nothing here places an order or touches an account — it
answers "what does the panel think?" against the bars already in the local
store, so the disagreement is visible before anyone decides to trust a blend of
it.

Deliberately defensive: a missing algo directory, an empty bar table or a member
that raises must degrade to an empty (or partial) panel, never to a 500. A
dashboard that cannot render because one contestant is broken is worse than
useless — it hides the eleven that are fine.
"""

from __future__ import annotations

import logging

from ..repository import TradingRepository

log = logging.getLogger("tradebot.web.consortium")

#: Building a panel costs one simulation pass per member, so the page caps the
#: history it reads. Enough to be meaningful, bounded enough to render.
DEFAULT_BARS = 250


def panel(
    repo: TradingRepository,
    algo_paths: list[str] | None = None,
    voice_name: str = "equal",
    limit: int = DEFAULT_BARS,
    mode: str | None = None,
) -> dict:
    """Every member's current recommendation, its voice, and the consensus."""
    from ...arena.loader import discover
    from ...arena.panel import build_panel, eligible_members
    from ...consortium import build_voice, consensus

    paths = algo_paths or ["./algos"]
    empty = {"members": [], "consensus": [], "symbols": [], "voice": voice_name,
             "bars": 0, "errors": []}

    try:
        found, load_errors = discover(paths)
    except Exception as exc:                     # noqa: BLE001 — surfaced, not raised
        log.warning("Could not load algos from %s: %s", paths, exc)
        return {**empty, "errors": [f"could not load {paths}: {exc}"]}

    members = eligible_members(found)
    frames = _frames(repo, limit=limit, mode=mode)
    if not members or not frames:
        return {**empty, "errors": [str(e) for e in load_errors]}

    try:
        built = build_panel(members, frames)
        voice = build_voice(voice_name).weights(built.curves)
        targets, weights = consensus(built.books, voice)
    except Exception as exc:                     # noqa: BLE001
        log.warning("Panel build failed: %s", exc)
        return {**empty, "errors": [f"panel build failed: {exc}"]}

    symbols = sorted(frames)
    latest = built.latest()
    last_voice = voice.iloc[-1] if len(voice) else {}
    rows = []
    for name in sorted(latest):
        book = latest[name]
        curve = built.curves[name]
        rows.append({
            "name": name,
            "voice": float(last_voice.get(name, 0.0)),
            "total_return": float(curve.iloc[-1] / curve.iloc[0] - 1.0)
            if len(curve) > 1 and curve.iloc[0] else 0.0,
            "book": {s: round(float(book.get(s, 0.0)), 4) for s in symbols},
        })
    rows.sort(key=lambda r: r["voice"], reverse=True)

    consensus_rows = [
        {"symbol": s,
         "target": int(targets[s].iloc[-1]) if s in targets else 0,
         "weight": round(float(weights[s].iloc[-1]), 4) if s in weights else 0.0}
        for s in symbols
    ]

    errors = [str(e) for e in load_errors]
    errors += [f"{name}: {why}" for name, why in built.failures.items()]
    return {
        "members": rows,
        "consensus": consensus_rows,
        "symbols": symbols,
        "voice": voice_name,
        "bars": len(next(iter(frames.values()))),
        "errors": errors,
    }


def _frames(repo: TradingRepository, limit: int, mode: str | None) -> dict:
    """Stored bars per symbol, aligned enough to simulate over."""
    import pandas as pd

    timeframes = repo.timeframes()
    timeframe = timeframes[0] if len(timeframes) == 1 else None
    frames = {}
    for symbol in repo.symbols():
        rows = repo.bars(symbol, mode=mode, timeframe=timeframe, limit=limit)
        if len(rows) < 3:
            continue
        idx = pd.to_datetime([r["ts"] for r in rows], utc=True)
        frames[symbol] = pd.DataFrame(
            [{"open": float(r["open"]), "high": float(r["high"]),
              "low": float(r["low"]), "close": float(r["close"]),
              "volume": float(r["volume"])} for r in rows],
            index=idx,
        ).sort_index()
    return frames
