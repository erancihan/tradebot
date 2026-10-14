"""``explain``: one sentence per proposal line, from structured parts."""

from __future__ import annotations


_SIGNAL_WORDS = {1: "long", 0: "flat", -1: "short"}


def explain(*, strategy, signal, action, selected=None, rank=None, weight=None,
            capped=False, banded=False) -> str:
    """A one-sentence reason (placeholder until the structured version)."""
    return f"{strategy} signals {_SIGNAL_WORDS.get(signal, signal)}; {action}."

