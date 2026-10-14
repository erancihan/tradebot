"""Combine many algorithms into one book, weighting them by voice.

The premise: don't bet on one algorithm. Run a panel of them, read what each
one *would* hold, and blend those books together. A member that loses money is
not thrown out — its voice shrinks, and it can recover. Membership is
permanent; influence is earned.

Three pieces:

- **Recommendation** — what a member would hold if it traded the whole account
  alone: a signed weight per symbol, as a fraction of equity. Produced by
  :mod:`tradebot.arena.panel`, which reads it out of the one place every
  contestant kind converges on.
- **Voice** — how much each member's opinion counts at each bar
  (:class:`EqualVoice`, :class:`HedgeVoice`).
- **Consensus** — the voice-weighted average of the member books.

The consensus is a *convex* combination of valid weight vectors, so it is
itself a valid weight vector — no renormalisation, and no way for the blend to
lever up beyond what its members were already asking for. Its sign gives the
target and its magnitude gives the conviction, which means **disagreement
shrinks a position rather than producing a coin flip**. That property is the
main reason a panel is worth having over a vote.

Sizing is not done here. The consensus is a *proposal*; `RiskManager` remains
the only place weights become share quantities.
"""

from __future__ import annotations

from .consensus import consensus
from .panel import Consortium, _ConsensusPolicy
from .voice import VOICES, EqualVoice, HedgeVoice, Voice, build_voice

__all__ = ["VOICES", "Consortium", "EqualVoice", "HedgeVoice", "Voice",
           "build_voice", "consensus"]
