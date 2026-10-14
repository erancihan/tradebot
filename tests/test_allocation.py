import numpy as np
import pandas as pd
import pytest

from tradebot.allocation import (
    EqualWeight,
    ExplicitWeights,
    InverseVolatility,
    build_allocator,
)


def _frame(closes) -> pd.DataFrame:
    values = np.asarray(closes, dtype=float)
    idx = pd.date_range("2024-01-01", periods=len(values), freq="1D", tz="UTC")
    return pd.DataFrame(
        {"open": values, "high": values, "low": values,
         "close": values, "volume": 1000.0},
        index=idx,
    )


def _wiggle(base: float, pct: float, periods: int) -> list[float]:
    """A price path alternating +pct/-pct around ``base`` (constant vol)."""
    out, price = [], base
    for i in range(periods):
        price = price * (1 + pct if i % 2 == 0 else 1 - pct)
        out.append(price)
    return out


# --- EqualWeight ----------------------------------------------------------------

def test_equal_weight_splits_across_active_only():
    alloc = EqualWeight()
    w = alloc.weights({"A": 1, "B": -1, "C": 0}, {})
    assert w == {"A": 0.5, "B": 0.5}


def test_equal_weight_respects_gross_target():
    alloc = EqualWeight(gross_target=0.6)
    w = alloc.weights({"A": 1, "B": 1}, {})
    assert w == {"A": 0.3, "B": 0.3}


def test_equal_weight_no_active_returns_empty():
    assert EqualWeight().weights({"A": 0}, {}) == {}


# --- InverseVolatility ------------------------------------------------------------

def test_inverse_vol_downweights_the_volatile_name():
    calm = _frame(_wiggle(100, 0.01, 40))
    wild = _frame(_wiggle(100, 0.02, 40))
    alloc = InverseVolatility(window=20)
    w = alloc.weights({"CALM": 1, "WILD": 1}, {"CALM": calm, "WILD": wild})
    assert w["CALM"] > w["WILD"]
    # Vol ratio is ~2:1, so weights should be ~2:1 the other way.
    assert w["CALM"] / w["WILD"] == pytest.approx(2.0, rel=0.15)
    assert sum(w.values()) == pytest.approx(1.0)


def test_inverse_vol_excludes_insufficient_history():
    long_hist = _frame(_wiggle(100, 0.01, 40))
    short_hist = _frame(_wiggle(100, 0.01, 5))   # < window: unmeasurable
    alloc = InverseVolatility(window=20)
    w = alloc.weights({"A": 1, "B": 1}, {"A": long_hist, "B": short_hist})
    assert "B" not in w
    assert w["A"] == pytest.approx(1.0)


def test_inverse_vol_all_unmeasurable_allocates_nothing():
    stub = _frame(_wiggle(100, 0.01, 3))
    alloc = InverseVolatility(window=20)
    assert alloc.weights({"A": 1}, {"A": stub}) == {}
    assert alloc.weights({"A": 1}, {"A": stub.iloc[:0]}) == {}   # empty history


# --- ExplicitWeights --------------------------------------------------------------

def test_explicit_weights_uses_mapping_and_defaults_missing_to_zero():
    alloc = ExplicitWeights({"SPY": 0.4, "QQQ": 0.3})
    w = alloc.weights({"SPY": 1, "QQQ": 1, "IWM": 1}, {})
    assert w == {"SPY": 0.4, "QQQ": 0.3, "IWM": 0.0}


def test_explicit_weights_validates():
    with pytest.raises(ValueError):
        ExplicitWeights({})
    with pytest.raises(ValueError):
        ExplicitWeights({"SPY": -0.1})
    with pytest.raises(ValueError):
        ExplicitWeights({"SPY": 1.5})


# --- registry ---------------------------------------------------------------------

def test_build_allocator_by_name_with_params():
    alloc = build_allocator("inverse_vol", {"window": 10, "gross_target": 0.8})
    assert isinstance(alloc, InverseVolatility)
    assert alloc.window == 10
    assert alloc.gross_target == 0.8


def test_build_allocator_unknown_name_raises():
    with pytest.raises(KeyError):
        build_allocator("markowitz_4000")
