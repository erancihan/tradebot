import os

import pytest

from tradebot.config import LIVE_CONFIRM_ENV, LIVE_CONFIRM_VALUE, Settings


def test_defaults_are_paper():
    s = Settings()
    assert s.mode == "paper"
    assert s.broker_is_paper is True
    assert not s.is_live


def test_from_dict_parses_strategy_and_risk():
    s = Settings.from_dict({
        "mode": "backtest",
        "symbols": ["AAPL", "MSFT"],
        "strategy": {"name": "rsi_reversion", "params": {"period": 7}},
        "risk": {"max_position_pct": 0.2, "max_daily_loss_pct": 0.05},
    })
    assert s.symbols == ["AAPL", "MSFT"]
    assert s.strategy_name == "rsi_reversion"
    assert s.strategy_params == {"period": 7}
    assert s.risk.max_position_pct == 0.2


def test_portfolio_block_builds_allocator():
    s = Settings.from_dict({
        "symbols": ["SPY", "QQQ"],
        "portfolio": {"allocation": "inverse_vol", "params": {"window": 21}},
    })
    assert s.allocation_name == "inverse_vol"
    assert s.allocation_params == {"window": 21}
    alloc = s.build_allocator()
    assert alloc is not None and alloc.window == 21


def test_no_portfolio_block_keeps_legacy_sizing():
    s = Settings.from_dict({"symbols": ["SPY"]})
    assert s.allocation_name is None
    assert s.build_allocator() is None
    assert s.selector_name is None
    assert s.build_selector() is None


def test_portfolio_selector_block_builds_selector():
    s = Settings.from_dict({
        "symbols": ["A", "B", "C"],
        "portfolio": {
            "allocation": "equal",
            "selector": {"name": "momentum",
                         "params": {"lookback": 60, "skip": 5, "top_k": 2}},
        },
    })
    sel = s.build_selector()
    assert sel is not None
    assert sel.top_k == 2 and sel.lookback == 60
    assert s.build_allocator() is not None


def test_portfolio_overlays_block_builds_chain():
    s = Settings.from_dict({
        "symbols": ["A", "B"],
        "portfolio": {
            "allocation": "equal",
            "overlays": [
                {"name": "sector_cap",
                 "params": {"max_sector_pct": 0.5, "sectors": {"A": "tech"}}},
                {"name": "vol_target", "params": {"target_vol": 0.2}},
            ],
        },
    })
    chain = s.build_overlays()
    assert [o.name for o in chain] == ["sector_cap", "vol_target"]


def test_overlays_without_allocation_are_rejected():
    import pytest as _pytest

    s = Settings.from_dict({
        "symbols": ["A"],
        "portfolio": {"overlays": [{"name": "vol_target"}]},
    })
    with _pytest.raises(ValueError, match="allocation"):
        s.build_overlays()

    from tradebot.backtest import Backtester
    from tradebot.overlays import VolTargetOverlay
    from tradebot.risk import RiskConfig, RiskManager
    from tradebot.strategies import SmaCrossover

    with _pytest.raises(ValueError, match="allocator"):
        Backtester(SmaCrossover(10, 30), RiskManager(RiskConfig()),
                   overlays=[VolTargetOverlay()])


def test_universe_block_builds_source():
    s = Settings.from_dict({
        "symbols": ["SPY"],
        "universe": {"source": "alpaca_liquidity",
                     "params": {"candidates": 40, "max_symbols": 10}},
    })
    uni = s.build_universe()
    assert uni is not None
    assert uni.candidates == 40
    assert uni.screen.max_symbols == 10

    plain = Settings.from_dict({"symbols": ["SPY"]})
    assert plain.universe_name is None
    assert plain.build_universe() is None


def test_invalid_mode_rejected():
    with pytest.raises(ValueError):
        Settings(mode="yolo")


def test_live_requires_confirmation(monkeypatch):
    monkeypatch.delenv(LIVE_CONFIRM_ENV, raising=False)
    s = Settings(mode="live")
    assert s.broker_is_paper is False
    with pytest.raises(PermissionError):
        s.require_live_ack()

    monkeypatch.setenv(LIVE_CONFIRM_ENV, LIVE_CONFIRM_VALUE)
    s.require_live_ack()  # now allowed


def test_paper_never_requires_ack():
    s = Settings(mode="paper")
    s.require_live_ack()  # no-op, must not raise
