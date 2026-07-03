import numpy as np
import pandas as pd
import pytest

from tradebot.overlays import (
    SectorCapOverlay,
    VolTargetOverlay,
    apply_overlays,
    build_overlay,
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
    out, price = [], base
    for i in range(periods):
        price = price * (1 + pct if i % 2 == 0 else 1 - pct)
        out.append(price)
    return out


# --- VolTargetOverlay ---------------------------------------------------------

def test_vol_dial_scales_down_a_hot_book():
    # ±3%/day is ~48% annualized; a 15% target should scale hard.
    hist = {"A": _frame(_wiggle(100, 0.03, 40)), "B": _frame(_wiggle(50, 0.03, 40))}
    dial = VolTargetOverlay(target_vol=0.15, window=20)
    out = dial.transform({"A": 0.5, "B": 0.5}, {"A": 1, "B": 1}, hist)
    assert out["A"] < 0.25 and out["B"] < 0.25
    assert out["A"] == pytest.approx(out["B"])          # proportional scaling


def test_vol_dial_never_levers_up_a_calm_book():
    hist = {"A": _frame(_wiggle(100, 0.001, 40))}       # ~1.6% annualized
    dial = VolTargetOverlay(target_vol=0.15, window=20)
    out = dial.transform({"A": 0.6}, {"A": 1}, hist)
    assert out == {"A": 0.6}                            # scale capped at 1.0


def test_vol_dial_passes_through_when_unmeasurable():
    dial = VolTargetOverlay(target_vol=0.15, window=20)
    short = {"A": _frame(_wiggle(100, 0.03, 5))}
    assert dial.transform({"A": 0.5}, {"A": 1}, short) == {"A": 0.5}
    assert dial.transform({}, {}, {}) == {}


def test_vol_dial_never_increases_any_weight():
    hist = {"A": _frame(_wiggle(100, 0.02, 40)), "B": _frame(_wiggle(80, 0.005, 40))}
    weights = {"A": 0.4, "B": 0.3}
    out = VolTargetOverlay(target_vol=0.10, window=20).transform(
        weights, {"A": 1, "B": 1}, hist)
    assert all(out[s] <= weights[s] + 1e-12 for s in weights)


# --- SectorCapOverlay -----------------------------------------------------------

def test_sector_cap_scales_only_the_offending_sector():
    cap = SectorCapOverlay(max_sector_pct=0.5,
                           sectors={"AAA": "tech", "BBB": "tech", "CCC": "energy"})
    out = cap.transform({"AAA": 0.4, "BBB": 0.4, "CCC": 0.2},
                        {"AAA": 1, "BBB": 1, "CCC": 1}, {})
    assert out["AAA"] == pytest.approx(0.25)            # 0.8 tech -> 0.5, pro-rata
    assert out["BBB"] == pytest.approx(0.25)
    assert out["CCC"] == pytest.approx(0.2)             # energy untouched


def test_sector_cap_buckets_unknown_symbols_together():
    cap = SectorCapOverlay(max_sector_pct=0.4, sectors={"AAA": "tech"})
    out = cap.transform({"AAA": 0.3, "XXX": 0.3, "YYY": 0.3},
                        {"AAA": 1, "XXX": 1, "YYY": 1}, {})
    # XXX+YYY share the 'other' bucket: 0.6 -> 0.4.
    assert out["XXX"] == pytest.approx(0.2)
    assert out["YYY"] == pytest.approx(0.2)
    assert out["AAA"] == pytest.approx(0.3)


def test_sector_cap_loads_csv(tmp_path):
    f = tmp_path / "sectors.csv"
    f.write_text("symbol,sector\naaa,tech\nBBB,energy\n")
    cap = SectorCapOverlay(max_sector_pct=0.5, sectors_file=str(f))
    assert cap.sectors == {"AAA": "tech", "BBB": "energy"}


def test_sector_cap_validates():
    with pytest.raises(ValueError):
        SectorCapOverlay(max_sector_pct=0.0, sectors={"A": "x"})
    with pytest.raises(ValueError):
        SectorCapOverlay(max_sector_pct=0.5)            # no mapping at all


# --- registry / chain ------------------------------------------------------------

def test_build_overlay_registry():
    dial = build_overlay("vol_target", {"target_vol": 0.2, "window": 10})
    assert isinstance(dial, VolTargetOverlay)
    assert dial.required_history == 11
    with pytest.raises(KeyError):
        build_overlay("crystal_shield")


def test_apply_overlays_chains_in_order():
    hist = {"A": _frame(_wiggle(100, 0.03, 40)), "B": _frame(_wiggle(50, 0.03, 40))}
    chain = [
        SectorCapOverlay(max_sector_pct=0.4, sectors={"A": "tech", "B": "tech"}),
        VolTargetOverlay(target_vol=0.15, window=20),
    ]
    out = apply_overlays(chain, {"A": 0.5, "B": 0.5}, {"A": 1, "B": 1}, hist)
    # Sector cap first (1.0 tech -> 0.4), then the dial shrinks further.
    assert out["A"] + out["B"] < 0.4
