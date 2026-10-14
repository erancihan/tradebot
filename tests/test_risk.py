import pytest

from tradebot.risk import RiskConfig, RiskManager


def rm(**kw) -> RiskManager:
    return RiskManager(RiskConfig(**kw))


def test_target_qty_sizes_to_position_fraction():
    r = rm(max_position_pct=0.10, allow_fractional=False)
    # 10% of 10_000 = 1_000 budget; at $50 -> 20 shares.
    assert r.target_qty(1, equity=10_000, price=50) == 20
    # Short target -> negative qty of same magnitude.
    assert r.target_qty(-1, equity=10_000, price=50) == -20
    # Flat target -> no position.
    assert r.target_qty(0, equity=10_000, price=50) == 0


def test_target_qty_floors_without_fractional():
    r = rm(max_position_pct=0.10, allow_fractional=False)
    # budget 1000 / price 30 = 33.3 -> floor 33.
    assert r.target_qty(1, equity=10_000, price=30) == 33


def test_target_qty_fractional_allows_partial_shares():
    r = rm(max_position_pct=0.10, allow_fractional=True)
    assert r.target_qty(1, equity=10_000, price=30) == pytest.approx(33.3333, rel=1e-3)


def test_exposure_clamp_limits_total():
    r = rm(max_position_pct=1.0, max_gross_exposure=1.0, allow_fractional=False)
    # Cap = equity*1.0 = 10_000; 6_000 already deployed -> room 4_000.
    # At $100 that is at most 40 shares even if we wanted 80.
    clamped = r.clamp_to_exposure(80, price=100, equity=10_000, current_gross=6_000)
    assert clamped == 40


def test_exposure_clamp_blocks_when_full():
    r = rm(max_gross_exposure=1.0, allow_fractional=False)
    assert r.clamp_to_exposure(50, price=100, equity=10_000, current_gross=10_000) == 0


def test_target_qty_with_weight_overrides_default():
    r = rm(max_position_pct=0.50, allow_fractional=False)
    # 20% of 10_000 = 2_000 at $50 -> 40 shares.
    assert r.target_qty(1, equity=10_000, price=50, weight=0.20) == 40
    # Weight is capped at max_position_pct: 0.9 -> 0.5 -> 100 shares.
    assert r.target_qty(1, equity=10_000, price=50, weight=0.90) == 100
    # Zero weight -> no position, even with a long target.
    assert r.target_qty(1, equity=10_000, price=50, weight=0.0) == 0


def test_allocate_defaults_match_per_symbol_sizing():
    r = rm(max_position_pct=0.10, max_gross_exposure=1.0)
    got = r.allocate({"A": 1, "B": -1, "C": 0}, equity=10_000,
                     prices={"A": 50, "B": 25, "C": 10})
    assert got == {
        "A": r.target_qty(1, 10_000, 50),
        "B": r.target_qty(-1, 10_000, 25),
        "C": 0.0,
    }


def test_allocate_is_order_independent():
    r = rm(max_position_pct=0.60, max_gross_exposure=1.0)
    prices = {"A": 100.0, "B": 50.0, "C": 20.0}
    targets = {"A": 1, "B": 1, "C": 1}
    forward = r.allocate(targets, 10_000, prices)
    reversed_ = r.allocate(dict(reversed(list(targets.items()))), 10_000, prices)
    assert forward == reversed_


def test_allocate_scales_book_to_gross_cap():
    # Two names wanting 0.6 each (1.2 gross) against a 1.0 cap -> 0.5 each.
    r = rm(max_position_pct=0.60, max_gross_exposure=1.0, allow_fractional=True)
    got = r.allocate({"A": 1, "B": 1}, equity=10_000, prices={"A": 100, "B": 100})
    assert got["A"] == pytest.approx(50.0)   # 0.5 * 10_000 / 100
    assert got["B"] == pytest.approx(50.0)


def test_allocate_uses_and_caps_provided_weights():
    r = rm(max_position_pct=0.30, max_gross_exposure=1.0, allow_fractional=True)
    got = r.allocate(
        {"A": 1, "B": 1, "C": 1}, equity=10_000,
        prices={"A": 100, "B": 100, "C": 100},
        weights={"A": 0.20, "B": 0.90},       # B capped to 0.30; C unfunded
    )
    assert got["A"] == pytest.approx(20.0)
    assert got["B"] == pytest.approx(30.0)
    assert got["C"] == 0.0


def test_material_delta_band_skips_drift_but_always_exits():
    r = rm(rebalance_band_pct=0.02, allow_fractional=True)
    # 1 share of drift at $100 on $10_000 equity = 1% < 2% band -> skip.
    assert r.material_delta(desired=51, current=50, price=100, equity=10_000) == 0.0
    # 5 shares = 5% > band -> trade the full delta.
    assert r.material_delta(desired=55, current=50, price=100, equity=10_000) == 5.0
    # Full exit always executes, however small.
    assert r.material_delta(desired=0, current=1, price=100, equity=10_000) == -1.0
    # Band off -> raw delta.
    assert rm().material_delta(51, 50, 100, 10_000) == 1.0


def test_daily_loss_circuit_breaker():
    r = rm(max_daily_loss_pct=0.03)
    assert not r.daily_loss_tripped(10_000, 9_800)   # -2% ok
    assert r.daily_loss_tripped(10_000, 9_700)       # -3% trips
    assert r.daily_loss_tripped(10_000, 9_500)       # worse trips


def test_riskconfig_validates_bounds():
    with pytest.raises(ValueError):
        RiskConfig(max_position_pct=1.5)
