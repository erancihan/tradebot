"""``propose``: the deltas one rebalance pass would submit, computed purely.

``Engine.rebalance`` calls this and then submits the lines, so a suggestion
and an execution come from one code path. Change behaviour here, never in
the engine.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime

from ..models import utcnow
from .explain import explain
from .types import Proposal, ProposalLine

log = logging.getLogger("tradebot.advisor")


def propose(*, symbols, frames, equity, positions, strategy, risk, selector=None,
            allocator=None, overlays=(), provenance=None, cash: float = 0.0,
            selector_frames=None, now: datetime | None = None) -> Proposal:
    """The deltas one rebalance pass would submit, computed without submitting.

    Pure: reads only its arguments, never a broker or a store. ``frames`` are
    the per-symbol bars the strategy sees; ``selector_frames`` is the longer
    accumulated history a ranked selector needs (it defaults to ``frames``).
    ``positions`` maps symbol -> signed quantity held. A symbol with no bars,
    a bad price or a failing signal is skipped with a reason and never sized.
    """
    if overlays and allocator is None:
        raise ValueError("overlays require an allocator (they transform its weights)")
    targets, prices, skipped = _signals(symbols, frames, strategy)
    signals = dict(targets)                        # before the selector gate
    live = {s: frames[s] for s in targets}
    pool = {s: (selector_frames or frames).get(s, frames[s]) for s in targets}
    members, ranks = _select(selector, targets, pool)
    weights = _weights(allocator, overlays, targets, live)
    desired = risk.allocate(targets, equity, prices, weights)
    capped = _capped(targets, weights, risk.config)

    lines: list[ProposalLine] = []
    for sym in dict.fromkeys(symbols):
        current = float(positions.get(sym, 0.0))
        if sym in skipped:
            lines.append(_skipped(sym, current, skipped[sym]))
            continue
        parts = {"strategy": strategy.name, "signal": signals[sym],
                 "selected": None if members is None else bool(members.get(sym)),
                 "rank": ranks.get(sym), "weight": None if weights is None
                 else weights.get(sym), "capped": capped.get(sym, False)}
        lines.append(_line(sym, targets[sym], current, desired[sym], prices[sym],
                           equity, risk, parts))
    return Proposal(created_at=now or utcnow(), equity=float(equity), cash=float(cash),
                    lines=lines, provenance=dict(provenance or {}), weights=weights)


def _signals(symbols, frames, strategy):
    """Latest target and price per symbol; failures are skipped, not fatal."""
    targets: dict[str, int] = {}
    prices: dict[str, float] = {}
    skipped: dict[str, str] = {}
    for sym in dict.fromkeys(symbols):
        bars = frames.get(sym)
        if bars is None or len(bars) == 0:
            skipped[sym] = "no bars"
            continue
        price = float(bars["close"].iloc[-1])
        # A NaN or non-positive price never reaches sizing: floor(NaN) raises.
        if not math.isfinite(price) or price <= 0:
            skipped[sym] = f"no valid price (got {price})"
            continue
        try:
            targets[sym] = int(strategy.latest_target(bars))
        except Exception as exc:  # noqa: BLE001 - one bad symbol never kills a pass
            log.exception("Signal failed for %s; skipping it this pass", sym)
            skipped[sym] = f"signal failed ({type(exc).__name__})"
            continue
        prices[sym] = price
    for sym, why in skipped.items():
        log.warning("%s skipped: %s", sym, why)
    return targets, prices, skipped


def _select(selector, targets: dict[str, int], pool: dict):
    """Force non-members flat in place; returns (membership, ranks)."""
    if selector is None:
        return None, {}
    members = selector.latest_targets(pool)
    for sym in targets:
        if not members.get(sym):
            targets[sym] = 0
    return members, _ranks(selector, pool)


def _ranks(selector, pool: dict) -> dict[str, tuple[int, int]]:
    """``symbol -> (rank, pool size)`` on the latest bar, for ranked selectors.

    Ordering matches ``RankedSelector._rank`` (score desc, then name) so the
    rank the reason quotes is the rank the selector acted on.
    """
    scores = getattr(selector, "scores", None)
    if scores is None or not pool:
        return {}
    try:
        row = scores(pool).iloc[-1].dropna()
    except Exception:  # noqa: BLE001 - a rank is decoration, never a blocker
        return {}
    ordered = sorted(row.index, key=lambda s: (-row[s], s))
    return {s: (i + 1, len(ordered)) for i, s in enumerate(ordered)}


def _weights(allocator, overlays, targets, frames):
    if allocator is None:
        return None
    weights = allocator.weights(targets, frames)
    for overlay in overlays:
        weights = overlay.transform(weights, targets, frames)
    return weights


def _capped(targets, weights, cfg) -> dict[str, bool]:
    """Whether a risk limit shrank each active symbol's requested weight.

    Mirrors ``RiskManager.allocate``: a per-name cap, then one proportional
    scale-down of the whole book when it exceeds the gross cap.
    """
    requested = {s: (cfg.max_position_pct if weights is None else weights.get(s, 0.0))
                 for s, t in targets.items() if t != 0}
    effective = sum(min(max(w, 0.0), cfg.max_position_pct) for w in requested.values())
    scaled = effective > cfg.max_gross_exposure
    return {s: scaled or w > cfg.max_position_pct for s, w in requested.items()}


def _line(sym, target, current, desired, price, equity, risk, parts) -> ProposalLine:
    material = risk.material_delta(desired, current, price, equity)
    delta = material if risk.config.allow_fractional else float(round(material))
    action = "buy" if delta > 0 else "sell" if delta < 0 else "hold"
    parts = {**parts, "banded": material == 0 and desired != current, "action": action}
    return ProposalLine(
        symbol=sym, action=action, target=target, current_qty=current,
        desired_qty=desired, order_qty=delta, price=price,
        notional=abs(delta) * price, weight=parts["weight"], reason=explain(**parts),
    )


def _skipped(sym: str, current: float, why: str) -> ProposalLine:
    return ProposalLine(
        symbol=sym, action="hold", target=0, current_qty=current, desired_qty=current,
        order_qty=0.0, price=0.0, notional=0.0, weight=None,
        reason=f"Skipped this pass: {why}.", skipped=True,
    )

