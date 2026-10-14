"""Per-scenario measurements the gate criteria are judged on.

Everything here is a pure function of one or two contestant results (or a
scenario's frames); the criteria in ``criteria.py`` only aggregate them.
"""

from __future__ import annotations

#: Fold counts the worst-fold comparison is re-run at, for the sensitivity line.
#: The verdict itself still uses the library default (4).
_SENSITIVITY_FOLDS = (3, 4, 5, 6, 7, 8)


def selector_activity(frames, top_k: int = 2) -> float | None:
    """Fraction of live bars on which two different selectors disagree.

    A scenario where every selector picks the same names cannot distinguish
    them, so a verdict comparing selection mechanisms over it carries no
    information. Both prior gauntlets scored ~0 here and nobody noticed for
    months, which is why the number is now printed next to every result rather
    than living only in a test.
    """
    from ...selection import LowVolatilitySelector, MomentumSelector

    if not frames or len(frames) <= top_k:
        return 0.0
    try:
        momentum = MomentumSelector(lookback=60, skip=5, top_k=top_k)
        low_vol = LowVolatilitySelector(window=30, top_k=top_k)
        warmup = max(momentum.required_history, low_vol.required_history)
        mom = momentum.membership(frames).iloc[warmup:]
        lov = low_vol.membership(frames).iloc[warmup:]
        if mom.empty:
            return 0.0
        return float((mom != lov).any(axis=1).mean())
    except Exception:      # a diagnostic must never break the verdict
        return None


def _first_active(result) -> int:
    """Index of the first bar on which this contestant actually held anything.

    Detected from the curve rather than declared, because the gate is handed
    results, not pipelines: equity sits exactly at `initial_cash` while a
    contestant is still warming up.
    """
    curve = result.equity_curve
    moved = curve.to_numpy() != result.initial_cash
    return int(moved.argmax()) if moved.any() else 0


def _rebased(result, start: int) -> dict:
    """Return/CAGR/drawdown/worst-fold measured from bar ``start`` onward.

    This is the warmup fix. `buy_and_hold` is deployed from bar 1 while a
    60-bar momentum selector is flat for 61 bars, so comparing whole curves
    credits the baseline with returns earned while the candidate was not yet
    trading. `walkforward.py` already gives each fold a warmup prefix; the gate
    did not. Scoring both contestants from the bar where the *later* of the two
    starts is the cheapest honest fix available to something holding only
    curves.

    Note the direction of the correction is not knowable in advance: it removes
    whatever the market did during the warmup, which may favour either side.
    """
    curve = result.equity_curve.iloc[start:]
    if len(curve) < 2:
        curve = result.equity_curve
    first, last = float(curve.iloc[0]), float(curve.iloc[-1])
    total = last / first - 1.0 if first else 0.0
    years = len(curve) / (result.periods_per_year or 252.0)
    cagr = (last / first) ** (1.0 / years) - 1.0 if first > 0 and years > 0 else 0.0
    peak = curve.cummax()
    drawdown = float((curve / peak - 1.0).min())

    rets = curve.pct_change().dropna()
    folds = []
    n = len(rets)
    if n:
        k = max(1, min(4, n))
        edges = [round(i * n / k) for i in range(k + 1)]
        folds = [float((1.0 + rets.iloc[lo:hi]).prod() - 1.0)
                 for lo, hi in zip(edges, edges[1:]) if hi > lo]
    return {"total": total, "cagr": cagr, "drawdown": drawdown,
            "worst_fold": min(folds) if folds else 0.0}


def _activity_for(scenario_obj) -> float | None:
    """Selector activity for a Scenario; None when only a name was passed."""
    build = getattr(scenario_obj, "build_frames", None)
    if build is None:
        return None
    try:
        return selector_activity(build())
    except Exception:
        return None


def _overlapping_spans(ok_rows: list[dict]) -> list[tuple[str, str]]:
    """Pairs of scenarios that are partly the same underlying price path.

    Only meaningful for *provider* data. Generated scenarios (`synthetic`,
    `factor`) share a calendar by construction — they are drawn onto one epoch —
    while being different worlds, so comparing dates alone flags every generated
    pair as a duplicate. Scenarios carved from one pulled span genuinely are one
    path counted several times (the real pack nests two windows inside a third),
    and only there does the mean double-count.
    """
    import pandas as pd

    generated = (None, "synthetic", "factor")
    dated = [r for r in ok_rows
             if r.get("span") and r.get("source") not in generated]
    clashes = []
    for i, a in enumerate(dated):
        lo_a, hi_a = (pd.Timestamp(t) for t in a["span"])
        for b in dated[i + 1:]:
            lo_b, hi_b = (pd.Timestamp(t) for t in b["span"])
            shared = set(a.get("symbols") or ()) & set(b.get("symbols") or ())
            if not shared:
                continue
            overlap = (min(hi_a, hi_b) - max(lo_a, lo_b)).total_seconds()
            shortest = min((hi_a - lo_a).total_seconds(),
                           (hi_b - lo_b).total_seconds())
            # Judge *material* overlap, not any touch. Adjacent calendar-year
            # windows brush by a day or two at the boundary; that is not one
            # price path counted twice, which is the thing worth warning about.
            if shortest > 0 and overlap / shortest > 0.05:
                clashes.append((a["scenario"], b["scenario"]))
    return clashes
