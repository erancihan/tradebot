"""Per-bar execution steps shared by both execution loops.

:class:`~tradebot.backtest.Backtester` and ``arena.simulation.simulate`` are
short orchestrations over the helpers in this module. Keeping every step that
touches fills, sizing or timing here makes the lockstep invariant structural:
a change to one loop's execution rules is a change to both.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

import numpy as np
import pandas as pd

from ..portfolio import Portfolio
from ..risk import RiskManager
from .result import BacktestResult, _infer_periods_per_year


def _sizing_marks(
    symbols,
    bar_opens: dict[str, float],
    prev_closes: dict[str, float],
    bar_closes: dict[str, float],
) -> dict[str, float]:
    """Prices to mark the book at when sizing a fill on this bar.

    Shared by :class:`Backtester` and ``arena.simulation.simulate`` so the two
    loops cannot drift apart — the lockstep invariant is structural here rather
    than merely asserted by a test.

    Order of preference per symbol: this bar's **open** (the price we are about
    to fill at, and already printed), then the **previous** bar's close, then
    this bar's close. That last fallback can only be reached on the first bar
    for a symbol with no usable open, when the book is still flat and the mark
    therefore cannot affect any quantity.

    Marking at this bar's close instead — which is what this loop used to do —
    sizes every fill with the return of the bar it fills on. The bias is not
    noise: it de-risks into down bars and levers into up bars, it scales with
    exposure and turnover so it does not cancel between a candidate and its
    benchmark, and it inflates results, so the failure mode is a false PASS.
    """
    marks = {}
    for s in symbols:
        price = bar_opens.get(s)
        if price is None:
            price = prev_closes.get(s, bar_closes[s])
        marks[s] = price
    return marks


def _prepare_components(aligned: dict, *components) -> None:
    """Give any component that wants it one look at the whole aligned frame set.

    Duck-typed, opt-in, and a no-op for everything that ships today. It exists
    for components whose per-bar answer is cheap only if a full-frame pass runs
    first — the consortium being the motivating case, where recomputing the
    member panel on every growing window would be quadratic.

    This is the same discipline selectors already get implicitly: `membership()`
    is called once over the full frame and then `.shift(1)`-ed, which is sound
    because the component is prefix-stable. **A component that uses this hook
    owes the same guarantee** — precompute freely, but never let bar `t`'s
    answer depend on a bar after `t`. Both execution loops call this at the same
    point, right after alignment, so the two cannot drift.

    Deduplicated by identity: one object may legitimately fill two roles at once
    (the consortium is its own signal *and* its own weighting, so it arrives as
    both the policy and the allocator). Preparing it twice would silently double
    the cost of the most expensive thing in the system — which is exactly how it
    first blew its time budget.
    """
    seen: set[int] = set()
    for component in components:
        if component is None or id(component) in seen:
            continue
        seen.add(id(component))
        prepare = getattr(component, "prepare", None)
        if callable(prepare):
            prepare(aligned)


def align_frames(frames: dict[str, pd.DataFrame], verb: str):
    """Reindex every symbol onto the intersection of their timelines.

    Align first, then decide: the strategy, the selector and the allocator must
    all see one timeline, or the vectorised loop diverges from the stepped one
    whenever real bars have ragged indexes.
    """
    common = None
    for df in frames.values():
        common = df.index if common is None else common.intersection(df.index)
    common = common.sort_values()
    if len(common) < 2:
        raise ValueError(f"Not enough overlapping bars to {verb}")
    return common, {s: df.reindex(common) for s, df in frames.items()}


def shifted_membership(selector, aligned: dict[str, pd.DataFrame]):
    """Selector verdicts on the one-bar shift: chosen on ``t``, gating ``t+1``.

    Precomputing over the full frame is sound only because selectors are
    prefix-stable.
    """
    if selector is None:
        return None
    return selector.membership(aligned).shift(1).fillna(False)


def fillable_targets(
    symbols: Iterable[str],
    i: int,
    opens: dict[str, pd.Series],
    target_of: Callable[[str], int],
    member,
) -> tuple[dict[str, int], dict[str, float]]:
    """This bar's fillable symbols, with targets gated by membership.

    A non-finite or non-positive open is skipped entirely: bad prices are flat
    everywhere, and must never reach sizing.
    """
    bar_targets: dict[str, int] = {}
    bar_prices: dict[str, float] = {}
    for s in symbols:
        price = float(opens[s].iloc[i])
        if not np.isfinite(price) or price <= 0:
            continue
        target = target_of(s)
        if member is not None and not bool(member[s].iloc[i]):
            target = 0
        bar_targets[s] = target
        bar_prices[s] = price
    return bar_targets, bar_prices


def book_weights(allocator, overlays, aligned, bar_targets: dict[str, int], i: int):
    """Allocator weights (then overlays) from bars strictly before fill bar ``i``.

    Weights obey the same one-bar shift as targets.
    """
    if allocator is None:
        return None
    history = {s: aligned[s].iloc[:i] for s in bar_targets}
    weights = allocator.weights(bar_targets, history)
    for overlay in overlays:
        weights = overlay.transform(weights, bar_targets, history)
    return weights


def fill_book(
    pf: Portfolio,
    risk: RiskManager,
    desired: dict[str, float],
    bar_prices: dict[str, float],
    equity: float,
    slip: float,
    commission: float,
) -> None:
    """Trade each symbol toward its desired quantity at this bar's open."""
    fractional = risk.config.allow_fractional
    for sym, want in desired.items():
        price = bar_prices[sym]
        delta = risk.material_delta(want, pf.position(sym).qty, price, equity)
        if fractional:
            if abs(delta) < 1e-9:
                continue
        else:
            delta = float(round(delta))
            if delta == 0:
                continue
        fill_price = price * (1 + slip) if delta > 0 else price * (1 - slip)
        pf.execute(sym, delta, fill_price, commission=commission)


def close_prices_at(closes: dict[str, pd.Series], i: int) -> dict[str, float]:
    """Each mark at bar ``i``: its close, past a bad print the last finite one
    (NaN only before any), so a NaN close never makes the next bar's sizing
    equity NaN in either loop (``floor(NaN)`` raises, a NaN book exits)."""
    out = {}
    for s, c in closes.items():
        price = float(c.iloc[i])
        if not np.isfinite(price) or price <= 0:
            prior = c.iloc[: i + 1]
            good = prior[np.isfinite(prior) & (prior > 0)]
            price = float(good.iloc[-1]) if len(good) else float("nan")
        out[s] = price
    return out


def build_result(points: list[float], common, pf: Portfolio, initial_cash: float,
                 cash_flows: pd.Series | None = None) -> BacktestResult:
    return BacktestResult(
        equity_curve=pd.Series(points, index=common, name="equity"),
        trades=pf.trades,
        initial_cash=initial_cash,
        periods_per_year=_infer_periods_per_year(common),
        cash_flows=cash_flows,
    )
