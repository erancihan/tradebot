"""The consortium: many algorithms blended into one book, weighted by voice.

The load-bearing properties, in order of how badly a break would hurt:

1. it cannot see the future (a panel is a decision rule like any other);
2. voice is causal — a member's performance on bar `t` cannot change its
   influence on bar `t`;
3. disagreement shrinks a position instead of producing a coin flip;
4. a member never disappears, so a silenced one can come back.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tradebot.arena.loader import discover
from tradebot.arena.panel import build_panel, eligible_members, is_consortium
from tradebot.consortium import (
    Consortium,
    EqualVoice,
    HedgeVoice,
    build_voice,
    consensus,
)
from tradebot.data.synthetic import synthetic_ohlcv

ALGOS = "./algos"
CONSORTIUM = "./algos/consortium"


def _frames(periods=90, seeds=(1, 2)):
    return {
        "AAA": synthetic_ohlcv(periods=periods, seed=seeds[0], drift=0.0012),
        "BBB": synthetic_ohlcv(periods=periods, seed=seeds[1], drift=-0.0008),
    }


def _curves(**members) -> pd.DataFrame:
    n = len(next(iter(members.values())))
    idx = pd.date_range("2023-01-02", periods=n, freq="1D", tz="UTC")
    return pd.DataFrame(members, index=idx)


def _book(index, **symbols) -> pd.DataFrame:
    return pd.DataFrame(symbols, index=index)


# --- voice ---------------------------------------------------------------------

def test_equal_voice_splits_evenly_and_sums_to_one():
    curves = _curves(a=[100, 101, 102], b=[100, 90, 80], c=[100, 105, 130])
    w = EqualVoice().weights(curves)

    assert np.allclose(w.to_numpy(), 1 / 3)
    assert w.sum(axis=1).tolist() == pytest.approx([1.0] * 3)


def test_hedge_voice_backs_the_winner_but_never_evicts_the_loser():
    winner = [100 * 1.02 ** i for i in range(30)]
    loser = [100 * 0.98 ** i for i in range(30)]
    w = HedgeVoice(eta=2.0, floor=0.02).weights(_curves(win=winner, lose=loser))

    final = w.iloc[-1]
    assert final["win"] > final["lose"]
    assert final["lose"] >= 0.02          # the floor: silenced, not evicted
    assert w.sum(axis=1).tolist() == pytest.approx([1.0] * len(w))


def test_a_silenced_member_can_recover():
    """Voice is a dimmer, not a door — the owner's requirement, made literal."""
    # Loses badly, then out-earns the other member for the rest of the run.
    revived = [100 * 0.95 ** i for i in range(20)] + [
        100 * 0.95 ** 19 * 1.15 ** i for i in range(1, 41)]
    steady = [100 * 1.001 ** i for i in range(60)]
    w = HedgeVoice(eta=2.0, floor=0.02).weights(_curves(revived=revived, steady=steady))

    # Equal voice would be 0.50 throughout. At its worst the member is cut to a
    # third of that, and it climbs back to dominating once it earns it.
    assert w["revived"].iloc[19] < 0.20
    assert w["revived"].iloc[-1] > 0.90


def test_hedge_voice_cannot_react_to_a_bar_it_has_not_seen():
    """Row t must depend only on rows strictly before t."""
    base = _curves(a=[100, 101, 102, 103, 104, 105], b=[100, 100, 100, 100, 100, 100])
    perturbed = base.copy()
    perturbed.iloc[4, 0] = 400.0              # a huge move on bar 4

    voice = HedgeVoice(eta=3.0, floor=0.0)
    before, after = voice.weights(base), voice.weights(perturbed)

    # Everything up to and including bar 4 is untouched; only bar 5 reacts.
    pd.testing.assert_frame_equal(before.iloc[:5], after.iloc[:5])
    assert after["a"].iloc[5] > before["a"].iloc[5]


def test_zero_learning_rate_reproduces_equal_voice():
    curves = _curves(a=[100, 120, 140], b=[100, 90, 70])
    pd.testing.assert_frame_equal(
        HedgeVoice(eta=0.0, floor=0.0).weights(curves), EqualVoice().weights(curves))


def test_an_unsatisfiable_floor_is_refused():
    curves = _curves(a=[100, 101], b=[100, 101], c=[100, 101])
    with pytest.raises(ValueError, match="unsatisfiable"):
        HedgeVoice(floor=0.5).weights(curves)


def test_voice_registry():
    assert isinstance(build_voice(None), EqualVoice)
    assert isinstance(build_voice("hedge", {"eta": 1.0}), HedgeVoice)
    with pytest.raises(ValueError, match="Unknown voice"):
        build_voice("wishful_thinking")


# --- consensus -----------------------------------------------------------------

def test_full_agreement_gives_full_conviction():
    idx = pd.date_range("2023-01-02", periods=3, freq="1D", tz="UTC")
    books = {"a": _book(idx, X=[0.8, 0.8, 0.8]), "b": _book(idx, X=[0.8, 0.8, 0.8])}
    voice = pd.DataFrame({"a": 0.5, "b": 0.5}, index=idx)

    targets, weights = consensus(books, voice)
    assert (targets["X"] == 1).all()
    assert weights["X"].tolist() == pytest.approx([0.8] * 3)


def test_a_split_panel_stands_aside():
    """Disagreement shrinks the position — it does not resolve to a coin flip."""
    idx = pd.date_range("2023-01-02", periods=2, freq="1D", tz="UTC")
    books = {"bull": _book(idx, X=[0.9, 0.9]), "bear": _book(idx, X=[-0.9, -0.9])}
    voice = pd.DataFrame({"bull": 0.5, "bear": 0.5}, index=idx)

    targets, weights = consensus(books, voice)
    assert (targets["X"] == 0).all()
    assert weights["X"].tolist() == pytest.approx([0.0, 0.0])


def test_partial_disagreement_scales_the_position_down():
    idx = pd.date_range("2023-01-02", periods=2, freq="1D", tz="UTC")
    books = {"a": _book(idx, X=[1.0, 1.0]), "b": _book(idx, X=[1.0, 1.0]),
             "c": _book(idx, X=[-1.0, -1.0])}
    voice = pd.DataFrame({"a": 1 / 3, "b": 1 / 3, "c": 1 / 3}, index=idx)

    targets, weights = consensus(books, voice)
    assert (targets["X"] == 1).all()                    # majority long
    assert weights["X"].tolist() == pytest.approx([1 / 3, 1 / 3])  # a third conviction


def test_the_blend_never_levers_beyond_its_members():
    """A convex combination of valid books is a valid book."""
    idx = pd.date_range("2023-01-02", periods=4, freq="1D", tz="UTC")
    rng = np.random.default_rng(0)
    books = {f"m{i}": _book(idx, X=rng.uniform(-0.9, 0.9, 4),
                            Y=rng.uniform(-0.9, 0.9, 4)) for i in range(5)}
    voice = EqualVoice().weights(pd.DataFrame(
        {name: [100.0] * 4 for name in books}, index=idx))

    _targets, weights = consensus(books, voice)
    assert (weights <= 0.9 + 1e-9).all().all()


# --- panel ---------------------------------------------------------------------

def test_the_panel_reads_every_contestant_kind():
    """Vectorized, event AND cross-sectional members, all one shape.

    This is the payoff of reading recommendations where the loop hands `desired`
    quantities to the RiskManager: a book is a book, whatever produced it.
    """
    members = eligible_members(discover([ALGOS])[0])
    kinds = {m.kind for m in members}
    assert kinds == {"vectorized", "event", "portfolio"}

    panel = build_panel(members, _frames())
    assert not panel.failures
    assert set(panel.books) == {m.name for m in members}
    for book in panel.books.values():
        assert list(book.columns) == ["AAA", "BBB"]
    assert set(panel.curves.columns) == {m.name for m in members}


def test_one_broken_member_does_not_kill_the_panel():
    """Surviving a bad member is the entire point of a panel."""
    class Exploding:
        required_history = 1

        def latest_target(self, bars):
            raise RuntimeError("member is on fire")

    from tradebot.arena.contestant import Contestant

    members = eligible_members(discover([ALGOS])[0])[:2]
    members.append(Contestant(name="broken", factory=Exploding, kind="vectorized"))

    panel = build_panel(members, _frames())
    assert "broken" in panel.failures
    assert "on fire" in panel.failures["broken"]
    assert len(panel.books) == 2          # the healthy members still read


def test_a_consortium_never_includes_itself():
    """Without this the loader recurses until the process dies."""
    found, _ = discover([ALGOS, CONSORTIUM])
    consortia = [c for c in found if is_consortium(c)]

    assert {c.name for c in consortia} == {"consortium", "consortium_hedge"}
    assert not any(is_consortium(m) for m in eligible_members(found))


def test_the_consortium_is_opt_in_and_not_part_of_the_field():
    """It costs the sum of its members, so it must not slow every tournament.

    Same arrangement as `algos/canaries/`: a subdirectory the non-recursive
    glob never reaches. This also keeps the field head-count that four other
    test files assert on.
    """
    field, _ = discover([ALGOS])
    assert not any(is_consortium(c) for c in field)
    assert len(field) == 12


# --- the contestant ------------------------------------------------------------

def _consortium_targets(frames, members=None):
    members = members or eligible_members(discover([ALGOS])[0])[:4]
    panel = Consortium(members)
    panel.prepare(frames)
    return panel.targets


def test_the_consortium_cannot_see_the_future():
    """The absolute guard: perturbing a late bar cannot move an early decision.

    `prepare()` gets the whole frame at once, which is exactly the shape that
    makes look-ahead easy to introduce by accident. Precomputing is only
    licensed because every member is causal; this asserts the licence holds.
    """
    frames = _frames(periods=80)
    before = _consortium_targets(frames)

    tampered = {s: df.copy() for s, df in frames.items()}
    tampered["AAA"].iloc[70:, tampered["AAA"].columns.get_loc("close")] *= 3.0
    tampered["AAA"].iloc[70:, tampered["AAA"].columns.get_loc("high")] *= 3.0
    after = _consortium_targets(tampered)

    pd.testing.assert_frame_equal(before.iloc[:70], after.iloc[:70])


def test_the_consensus_is_prefix_stable():
    """Recomputing on a prefix reproduces the prefix — same rule as selectors."""
    frames = _frames(periods=80)
    full = _consortium_targets(frames)
    prefix = _consortium_targets({s: df.iloc[:60] for s, df in frames.items()})

    pd.testing.assert_frame_equal(full.iloc[:60], prefix, check_freq=False)


def test_the_consortium_runs_as_an_ordinary_contestant():
    from tradebot.arena.adapters import simulation_args
    from tradebot.arena.simulation import SimConfig, simulate
    from tradebot.risk import RiskConfig, RiskManager

    found, _ = discover([CONSORTIUM])
    entry = [c for c in found if c.name == "consortium"][0]
    policy, extra = simulation_args(entry)

    result = simulate(
        policy, _frames(periods=60),
        RiskManager(RiskConfig(max_position_pct=0.95, max_daily_loss_pct=1.0)),
        SimConfig(initial_cash=10_000.0), **extra,
    )
    assert len(result.equity_curve) == 60
    assert result.final_equity > 0


def test_the_two_variants_differ_only_in_voice():
    found, _ = discover([CONSORTIUM])
    equal = [c for c in found if c.name == "consortium"][0].make()
    hedge = [c for c in found if c.name == "consortium_hedge"][0].make()

    assert isinstance(equal.strategy.voice, EqualVoice)
    assert isinstance(hedge.strategy.voice, HedgeVoice)
    assert {m.name for m in equal.strategy.members} == {m.name for m in hedge.strategy.members}
    # Same family, so the journal counts their attempts against one idea.
    families = {c.family for c in found if c.name.startswith("consortium")}
    assert families == {"consortium"}


def test_a_component_filling_two_roles_is_prepared_once():
    """The consortium is its own signal AND its own weighting, so it arrives at
    `_prepare_components` twice. Preparing it twice silently doubles the cost of
    the most expensive object in the system — which is how it first blew its
    time budget on the factor library.
    """
    from tradebot.backtest import _prepare_components

    class Counter:
        def __init__(self):
            self.calls = 0

        def prepare(self, aligned):
            self.calls += 1

    both = Counter()
    other = Counter()
    _prepare_components({}, both, other, both, None, both)

    assert both.calls == 1
    assert other.calls == 1


def test_the_consortium_prepares_once_per_simulation():
    from tradebot.arena.adapters import simulation_args
    from tradebot.arena.simulation import SimConfig, simulate
    from tradebot.risk import RiskConfig, RiskManager

    found, _ = discover([CONSORTIUM])
    entry = [c for c in found if c.name == "consortium"][0]
    policy, extra = simulation_args(entry)

    # The consortium reaches the loop as TWO objects — the policy wrapper and
    # the allocator — so identity dedup alone cannot save it. What must be
    # counted is the expensive part: how many times the panel is actually built.
    assert policy._consortium is extra["allocator"]

    import tradebot.arena.panel as panel_mod

    builds = []
    original = panel_mod.build_panel
    panel_mod.build_panel = lambda *a, **kw: (builds.append(1), original(*a, **kw))[1]
    try:
        simulate(policy, _frames(periods=40),
                 RiskManager(RiskConfig(max_position_pct=0.95, max_daily_loss_pct=1.0)),
                 SimConfig(initial_cash=10_000.0), **extra)
    finally:
        panel_mod.build_panel = original

    assert len(builds) == 1
