"""``explain``: one sentence per proposal line, from structured parts.

The reason is assembled from what each layer decided (strategy signal,
selector verdict, allocator weight, risk cap, no-trade band) rather than from
per-strategy prose, so every strategy gets an honest reason for free and the
sentence can never claim a step that did not run.
"""

from __future__ import annotations

SIGNAL_WORDS = {1: "long", 0: "flat", -1: "short"}


def explain(*, strategy: str, signal: int, action: str, selected: bool | None = None,
            rank: tuple[int, int] | None = None, weight: float | None = None,
            capped: bool = False, banded: bool = False) -> str:
    """E.g. ``"sma_crossover signals long; rank 2 of 5, weight 23%, capped by
    the risk limit; buy."``

    ``selected`` is None without a selector; ``rank`` is ``(k, N)`` when the
    selector ranks its pool. ``banded`` means the delta was real but smaller
    than the no-trade band, so the line holds.
    """
    head = f"{strategy} signals {SIGNAL_WORDS.get(signal, str(signal))}"
    middle: list[str] = []
    if selected is not None:
        where = f"rank {rank[0]} of {rank[1]}" if rank else ""
        if selected:
            middle.append(where or "selected")
        else:
            middle.append(f"not selected ({where})" if where else "not selected")
    active = signal != 0 and selected is not False
    if active and weight is not None:
        middle.append(f"weight {weight:.0%}")
    if active and capped:
        middle.append("capped by the risk limit")
    outcome = "within band, hold" if banded else action
    return "; ".join([head, *([", ".join(middle)] if middle else []), outcome]) + "."
