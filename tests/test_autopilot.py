"""Autopilot runner: passes on a timer inside market hours, offline.

Every test drives a real Engine over a DryRunBroker and ReplayData with a fake
clock and a sleep that only advances that clock, so the whole loop (market
hours, scheduling, errors) runs without a network or a wall clock.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

import pytest

from tradebot.autopilot import Autopilot
from tradebot.broker import DryRunBroker
from tradebot.config import Settings
from tradebot.data import ReplayData
from tradebot.data.synthetic import synthetic_ohlcv
from tradebot.engine import Engine
from tradebot.risk import RiskConfig, RiskManager
from tradebot.storage import Storage
from tradebot.strategies import build_strategy

SYMBOLS = ("A", "B")
#: Wednesday 2026-10-14, 11:00 New York: a regular session, well inside hours.
OPEN_NOW = datetime(2026, 10, 14, 15, 0, tzinfo=timezone.utc)
#: Saturday 2026-10-17, noon UTC: closed until Monday's open.
WEEKEND = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self.now = now
        self.slept: list[float] = []

    def __call__(self) -> datetime:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += timedelta(seconds=seconds)


class Recorder:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def send(self, event: dict) -> None:
        self.events.append(event)


def build(tmp_path, *, now=OPEN_NOW, poll=300, risk: RiskConfig | None = None,
          storage: Storage | None = None):
    frames = {s: synthetic_ohlcv(periods=80, drift=0.001, volatility=0.01, seed=i)
              for i, s in enumerate(SYMBOLS)}
    data = ReplayData(frames, warmup=60)
    broker = DryRunBroker(data, initial_cash=10_000, slippage_bps=0)
    risk = risk or RiskConfig(max_position_pct=0.4, max_gross_exposure=0.9)
    settings = Settings(mode="paper", symbols=list(SYMBOLS), risk=risk)
    storage = storage or Storage(tmp_path / "t.db")
    notifier = Recorder()
    engine = Engine(settings, broker, data, build_strategy("buy_and_hold", {}),
                    RiskManager(risk), storage, mode_label="dry_run",
                    enforce_live_ack=False, notifier=notifier)
    clock = FakeClock(now)
    pilot = Autopilot(engine, storage, poll_seconds=poll, clock=clock, sleep=clock.sleep)
    return pilot, broker, clock, notifier


def test_a_fresh_autopilot_is_off_and_does_nothing(tmp_path):
    pilot, broker, _, _ = build(tmp_path)
    state = pilot.tick()
    assert state.mode == "off" and state.last_pass_at is None
    assert broker._order_seq == 0


def test_tick_in_auto_mode_submits_every_line(tmp_path):
    pilot, broker, _, _ = build(tmp_path)
    pilot.set_mode("auto")
    state = pilot.tick()
    assert broker._order_seq == len(SYMBOLS)            # one buy per symbol
    assert set(broker.positions()) == set(SYMBOLS)
    assert state.last_pass_at == OPEN_NOW and state.last_error is None
    assert state.next_pass_at == OPEN_NOW + timedelta(seconds=300)
    assert state.pending == 0


def test_tick_in_approve_mode_stores_pending_and_submits_nothing(tmp_path):
    pilot, broker, _, _ = build(tmp_path)
    pilot.set_mode("approve")
    state = pilot.tick()
    assert broker._order_seq == 0
    assert state.pending == len(SYMBOLS)
    pending = pilot.storage.pending_lines("dry_run")
    assert {ln["symbol"] for ln in pending} == set(SYMBOLS)
    assert all(ln["action"] == "buy" for ln in pending)


def test_rebalance_without_submit_parks_lines_and_submit_lines_sends_them(tmp_path):
    pilot, broker, _, _ = build(tmp_path)
    engine, storage = pilot.engine, pilot.storage
    assert engine.rebalance(submit=False) == []
    pending = storage.pending_lines("dry_run")
    actions = engine.submit_lines([pending[0]["id"]])
    assert [a.symbol for a in actions] == [pending[0]["symbol"]]
    assert broker._order_seq == 1
    assert [ln["id"] for ln in storage.pending_lines("dry_run")] == [pending[1]["id"]]
    assert engine.submit_lines([pending[0]["id"]]) == []    # a double tap orders once


def test_loop_sleeps_through_a_closed_market_with_an_injected_clock(tmp_path):
    pilot, broker, clock, _ = build(tmp_path, now=WEEKEND)
    pilot.set_mode("auto")
    ticks = pilot.run_forever(max_ticks=2)
    monday_open = datetime(2026, 10, 19, 13, 30, tzinfo=timezone.utc)   # 09:30 EDT
    assert ticks == 2
    assert clock.slept == [(monday_open - WEEKEND).total_seconds()]
    assert pilot.state().last_pass_at == monday_open      # passed once, at the open
    assert broker._order_seq == len(SYMBOLS)
    assert not pilot.running


def test_next_pass_after_the_close_is_the_next_open(tmp_path):
    late = datetime(2026, 10, 14, 19, 58, tzinfo=timezone.utc)      # 15:58 EDT
    pilot, _, _, _ = build(tmp_path, now=late)
    pilot.set_mode("auto")
    state = pilot.tick()
    assert state.last_pass_at == late
    assert state.next_pass_at == datetime(2026, 10, 15, 13, 30, tzinfo=timezone.utc)


def test_a_failing_pass_is_recorded_and_the_loop_keeps_going(tmp_path, monkeypatch):
    pilot, _, _, _ = build(tmp_path)
    pilot.set_mode("auto")
    calls = []

    def explode(**kw):
        calls.append(kw)
        raise RuntimeError("broker unreachable")

    monkeypatch.setattr(pilot.engine, "step", explode)
    assert pilot.run_forever(max_ticks=3) == 3
    assert len(calls) == 3
    state = pilot.state()
    assert state.last_error == "RuntimeError: broker unreachable"
    assert state.mode == "auto"                        # still on: the next pass may work


def test_off_ends_the_loop_at_the_next_wake(tmp_path):
    pilot, _, clock, _ = build(tmp_path)
    pilot.set_mode("auto")
    pilot._sleep = lambda s: pilot.set_mode("off")      # the user taps Off mid-sleep
    assert pilot.run_forever(max_ticks=10) == 1


def test_state_round_trips_through_storage_across_restart(tmp_path):
    pilot, _, _, _ = build(tmp_path)
    pilot.set_mode("approve")
    pilot.tick()
    before = pilot.state()
    pilot.storage.close()
    again, _, _, _ = build(tmp_path, storage=Storage(tmp_path / "t.db"))
    after = again.state()
    assert after.mode == "approve"
    assert after.last_pass_at == before.last_pass_at
    assert after.next_pass_at == before.next_pass_at
    assert after.pending == before.pending == len(SYMBOLS)
    assert after.running is False                      # only this process knows that


def test_background_thread_starts_once_and_stops(tmp_path):
    shared = Storage(tmp_path / "t.db", check_same_thread=False)
    pilot, broker, _, _ = build(tmp_path, storage=shared)
    passed = threading.Event()
    pilot._sleep = lambda s: (passed.set(), pilot._stop.wait(s))  # stop-aware sleep
    pilot.set_mode("auto")
    assert pilot.start() is True
    assert pilot.start() is False                      # already running
    assert passed.wait(5)
    assert pilot.state().running is True
    pilot.set_mode("off")
    pilot._thread.join(5)
    assert not pilot._thread.is_alive() and not pilot.running
    assert broker._order_seq == len(SYMBOLS)           # the thread really passed


@pytest.mark.parametrize("bad", ["live", "on", ""])
def test_set_mode_refuses_anything_but_the_three_modes(tmp_path, bad):
    pilot, _, _, _ = build(tmp_path)
    with pytest.raises(ValueError):
        pilot.set_mode(bad)
