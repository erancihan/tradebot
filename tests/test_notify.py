"""Notifications: the bot can tell someone it acted, and can never be stopped by it.

The webhook adapter is exercised against a real ``http.server`` bound to
127.0.0.1 — the offline guard in conftest allows loopback exactly so that
adapters like this can be tested for real rather than through a mock that would
also pass if the code posted nothing at all.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pandas as pd
import pytest

from tradebot.config import Settings
from tradebot.engine import Engine
from tradebot.notify import (
    LogNotifier,
    MultiNotifier,
    NullNotifier,
    WebhookNotifier,
    build_notifier,
)
from tradebot.risk import RiskConfig, RiskManager
from tradebot.strategies import build_strategy


class Recorder:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def send(self, event: dict) -> None:
        self.events.append(event)


class Exploding:
    def send(self, event: dict) -> None:
        raise RuntimeError("endpoint on fire")


class MovingBars:
    def __init__(self, bars: list[dict]) -> None:
        self.bars = list(bars)

    def push(self, price: float) -> None:
        self.bars.append({"open": price, "high": price, "low": price, "close": price})

    def history(self, symbol, timeframe=None, lookback=None):
        idx = pd.date_range("2024-01-01", periods=len(self.bars), freq="1D", tz="UTC")
        return pd.DataFrame([{**b, "volume": 1000.0} for b in self.bars], index=idx)[
            ["open", "high", "low", "close", "volume"]
        ]


# --- adapters ------------------------------------------------------------------

def test_log_and_null_notifiers_accept_anything():
    LogNotifier().send({"type": "order", "symbol": "SPY"})
    NullNotifier().send({"type": "halt"})


def test_multi_notifier_survives_a_failing_member():
    good = Recorder()
    MultiNotifier([Exploding(), good]).send({"type": "order"})
    assert good.events == [{"type": "order"}]


def test_build_notifier_defaults_to_log_only():
    assert isinstance(build_notifier(None), LogNotifier)
    assert isinstance(build_notifier("http://127.0.0.1:1/hook"), MultiNotifier)


def test_webhook_posts_the_event_as_json():
    received: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):                       # noqa: N802 (stdlib naming)
            length = int(self.headers.get("Content-Length", 0))
            received.append(json.loads(self.rfile.read(length)))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):            # keep the test output quiet
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.handle_request, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/hook"
        WebhookNotifier(url, timeout=5).send({"type": "order", "symbol": "SPY", "qty": 3})
    finally:
        server.server_close()

    assert received == [{"type": "order", "symbol": "SPY", "qty": 3}]


def test_webhook_failure_is_swallowed():
    """An unreachable endpoint must not raise — a notifier is an observer."""
    # Port 1 on loopback: connection refused, no network egress, no waiting.
    WebhookNotifier("http://127.0.0.1:1/hook", timeout=1).send({"type": "order"})


# --- engine integration --------------------------------------------------------

def _engine(bars, broker, notifier, **risk_kwargs) -> Engine:
    settings = Settings(mode="paper", symbols=["SPY"], strategy_name="buy_and_hold")
    return Engine(
        settings, broker, bars, build_strategy("buy_and_hold", {}),
        RiskManager(RiskConfig(max_position_pct=0.9, **risk_kwargs)),
        storage=None, mode_label="dry_run", enforce_live_ack=False, notifier=notifier,
    )


def test_engine_emits_an_event_per_submitted_order():
    from tradebot.broker import DryRunBroker

    bars = MovingBars([{"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0}])
    broker = DryRunBroker(bars, initial_cash=10_000, slippage_bps=0)
    recorder = Recorder()
    _engine(bars, broker, recorder).rebalance()

    orders = [e for e in recorder.events if e["type"] == "order"]
    assert len(orders) == 1
    assert orders[0]["symbol"] == "SPY"
    assert orders[0]["side"] == "buy"
    assert orders[0]["mode"] == "dry_run"


def test_engine_emits_a_halt_event_when_the_breaker_trips():
    from tradebot.broker import DryRunBroker

    bars = MovingBars([{"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0}])
    broker = DryRunBroker(bars, initial_cash=10_000, slippage_bps=0)
    recorder = Recorder()
    engine = _engine(bars, broker, recorder, max_daily_loss_pct=0.02)
    engine.rebalance()                    # opens the position, sets session equity

    bars.push(50.0)                       # a 45% equity hit, far past the 2% limit
    assert engine.rebalance() == []

    halts = [e for e in recorder.events if e["type"] == "halt"]
    assert len(halts) == 1
    assert halts[0]["reason"] == "daily_loss"
    assert halts[0]["equity"] < halts[0]["start_equity"]


def test_a_failing_notifier_cannot_break_a_rebalance():
    from tradebot.broker import DryRunBroker

    bars = MovingBars([{"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0}])
    broker = DryRunBroker(bars, initial_cash=10_000, slippage_bps=0)
    actions = _engine(bars, broker, Exploding()).rebalance()

    assert [a.symbol for a in actions] == ["SPY"]
    assert not broker.position("SPY").is_flat          # the order still went through


def test_bracket_exits_are_notified():
    from tradebot.broker import DryRunBroker

    bars = MovingBars([{"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0}])
    broker = DryRunBroker(bars, initial_cash=10_000, slippage_bps=0)
    recorder = Recorder()
    engine = _engine(bars, broker, recorder, stop_loss_pct=0.05)
    engine.rebalance()

    bars.bars.append({"open": 99.0, "high": 99.0, "low": 90.0, "close": 92.0})
    engine.rebalance()

    exits = [e for e in recorder.events if e["type"] == "bracket_exit"]
    assert len(exits) == 1
    assert exits[0]["price"] == pytest.approx(95.0)


def test_config_reads_the_notify_block():
    settings = Settings.from_dict({"notify": {"webhook_url": "http://127.0.0.1:9/x"}})
    assert settings.notify_webhook_url == "http://127.0.0.1:9/x"
    assert isinstance(settings.build_notifier(), MultiNotifier)
    assert isinstance(Settings.from_dict({}).build_notifier(), LogNotifier)
