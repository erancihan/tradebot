import numpy as np
import pandas as pd
import pytest

from tradebot.selection import LowVolatilitySelector, MomentumSelector, build_selector


def _frame(closes) -> pd.DataFrame:
    values = np.asarray(closes, dtype=float)
    idx = pd.date_range("2024-01-01", periods=len(values), freq="1D", tz="UTC")
    return pd.DataFrame(
        {"open": values, "high": values, "low": values,
         "close": values, "volume": 1000.0},
        index=idx,
    )


def _trend(start: float, step: float, periods: int) -> list[float]:
    return [start + step * i for i in range(periods)]


def _pool(periods=40):
    # Momentum ordering by construction: UP > FLAT > DOWN.
    return {
        "UP": _frame(_trend(100, 1.0, periods)),
        "FLAT": _frame(_trend(100, 0.0, periods)),
        "DOWN": _frame(_trend(100, -1.0, periods)),
    }


def test_momentum_selects_the_top_k():
    sel = MomentumSelector(lookback=20, skip=2, top_k=1)
    member = sel.membership(_pool())
    last = member.iloc[-1]
    assert bool(last["UP"]) and not bool(last["FLAT"]) and not bool(last["DOWN"])

    sel2 = MomentumSelector(lookback=20, skip=2, top_k=2, exit_rank=2)
    last2 = sel2.membership(_pool()).iloc[-1]
    assert bool(last2["UP"]) and bool(last2["FLAT"]) and not bool(last2["DOWN"])


def test_momentum_needs_full_lookback():
    sel = MomentumSelector(lookback=20, skip=2, top_k=1)
    member = sel.membership(_pool(periods=40))
    # No symbol is measurable before `lookback` bars: nothing selected.
    assert not member.iloc[:20].to_numpy().any()
    assert member.iloc[-1].to_numpy().any()


def test_latest_targets_matches_membership_last_row():
    sel = MomentumSelector(lookback=20, skip=2, top_k=1)
    pool = _pool()
    assert sel.latest_targets(pool) == {"UP": 1, "FLAT": 0, "DOWN": 0}


def test_hysteresis_keeps_a_slipping_holder():
    """A holding that dips to rank K+1 (within exit_rank) must not churn out."""
    periods = 60
    # A leads early, then B overtakes; A stays within the exit band.
    a = [100 + 1.0 * i for i in range(30)] + [130 + 0.4 * i for i in range(30)]
    b = [100 + 0.2 * i for i in range(30)] + [106 + 2.0 * i for i in range(30)]
    c = [100 - 0.5 * i for i in range(periods)]
    pool = {"A": _frame(a), "B": _frame(b), "C": _frame(c)}

    banded = MomentumSelector(lookback=20, skip=0, top_k=1, exit_rank=2)
    m = banded.membership(pool)
    # Once measurable, A is picked; when B overtakes, A is rank 2 <= exit_rank,
    # so with the band A is retained the whole way.
    assert bool(m["A"].iloc[-1])
    assert not bool(m["B"].iloc[-1])

    strict = MomentumSelector(lookback=20, skip=0, top_k=1, exit_rank=1)
    m2 = strict.membership(pool)
    # Without the band the overtake swaps the holding to B.
    assert bool(m2["B"].iloc[-1])
    assert not bool(m2["A"].iloc[-1])


def test_membership_is_prefix_stable_no_lookahead():
    """Recomputing on any prefix must reproduce that prefix of the full run."""
    sel = MomentumSelector(lookback=15, skip=3, top_k=2)
    pool = _pool(periods=50)
    full = sel.membership(pool)
    for cut in (20, 33, 47):
        prefix = sel.membership({s: f.iloc[:cut] for s, f in pool.items()})
        pd.testing.assert_frame_equal(full.iloc[:cut], prefix)


def test_ties_break_deterministically():
    sel = MomentumSelector(lookback=10, skip=0, top_k=1)
    same = _trend(100, 1.0, 30)                    # identical series -> exact tie
    pool = {"ZZZ": _frame(same), "AAA": _frame(same)}
    assert sel.latest_targets(pool) == {"AAA": 1, "ZZZ": 0}   # alphabetical


def test_reverse_momentum_holds_the_losers():
    sel = MomentumSelector(lookback=20, skip=2, top_k=1, reverse=True)
    assert sel.latest_targets(_pool()) == {"UP": 0, "FLAT": 0, "DOWN": 1}


def test_low_vol_selects_the_calmest():
    rng = np.random.default_rng(7)
    base = 100 + np.arange(60) * 0.1
    pool = {
        "CALM": _frame(base + rng.normal(0, 0.05, 60)),
        "WILD": _frame(base + rng.normal(0, 5.0, 60)),
    }
    sel = LowVolatilitySelector(window=20, top_k=1)
    assert sel.latest_targets(pool) == {"CALM": 1, "WILD": 0}
    # Nothing is selected before a full window of returns exists.
    member = sel.membership(pool)
    assert not member.iloc[:20].to_numpy().any()


def test_ranked_selectors_are_prefix_stable():
    pool = _pool(periods=50)
    for sel in (MomentumSelector(lookback=15, skip=3, top_k=2, reverse=True),
                LowVolatilitySelector(window=12, top_k=2)):
        full = sel.membership(pool)
        for cut in (20, 33, 47):
            prefix = sel.membership({s: f.iloc[:cut] for s, f in pool.items()})
            pd.testing.assert_frame_equal(full.iloc[:cut], prefix)


def test_selector_validation_and_registry():
    with pytest.raises(ValueError):
        MomentumSelector(lookback=10, skip=10)
    with pytest.raises(ValueError):
        MomentumSelector(top_k=0)
    with pytest.raises(ValueError):
        MomentumSelector(top_k=5, exit_rank=3)
    with pytest.raises(ValueError):
        LowVolatilitySelector(window=1)
    sel = build_selector("momentum", {"lookback": 30, "skip": 5, "top_k": 2})
    assert isinstance(sel, MomentumSelector)
    assert sel.required_history == 31
    lv = build_selector("low_vol", {"window": 21, "top_k": 3})
    assert isinstance(lv, LowVolatilitySelector)
    assert lv.required_history == 22
    with pytest.raises(KeyError):
        build_selector("crystal_ball")
