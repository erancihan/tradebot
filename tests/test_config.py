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
