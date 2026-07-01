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


def test_daily_loss_circuit_breaker():
    r = rm(max_daily_loss_pct=0.03)
    assert not r.daily_loss_tripped(10_000, 9_800)   # -2% ok
    assert r.daily_loss_tripped(10_000, 9_700)       # -3% trips
    assert r.daily_loss_tripped(10_000, 9_500)       # worse trips


def test_riskconfig_validates_bounds():
    with pytest.raises(ValueError):
        RiskConfig(max_position_pct=1.5)
