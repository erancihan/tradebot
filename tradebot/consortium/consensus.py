"""The voice-weighted blend of member books."""

from __future__ import annotations

import numpy as np
import pandas as pd


def consensus(
    books: dict[str, pd.DataFrame], voice: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Blend member books into one. Returns ``(targets, weights)``.

    ``books`` maps member name to a bars × symbols frame of signed weights;
    ``voice`` is bars × members. The blend is
    ``score(s, t) = Σ_m voice_m(t) · book_m(s, t)`` — a convex combination, so
    the result is already a valid weight vector.

    ``targets`` is the sign of that score (staying in {-1, 0, +1}, because
    strategies never size anything) and ``weights`` is its magnitude: full
    agreement gives a full-conviction position, a split panel gives a small one,
    and a perfectly divided panel stands aside.
    """
    if not books:
        raise ValueError("consensus needs at least one member book")

    names = [m for m in books if m in voice.columns]
    if not names:
        raise ValueError("no member has a voice column")

    index = voice.index
    symbols = sorted({s for m in names for s in books[m].columns})
    score = pd.DataFrame(0.0, index=index, columns=symbols)
    for member in names:
        book = books[member].reindex(index=index, columns=symbols).fillna(0.0)
        score = score.add(book.mul(voice[member], axis=0), fill_value=0.0)

    targets = score.apply(np.sign).fillna(0.0).astype(int)
    return targets, score.abs()
