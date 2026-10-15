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
from tradebot.cli import main
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


# --- approve first ---------------------------------------------------------------

def _approve_pass(tmp_path, **kw):
    pilot, broker, clock, notifier = build(tmp_path, **kw)
    pilot.set_mode("approve")
    pilot.tick()
    return pilot, broker, clock, notifier, pilot.storage.pending_lines("dry_run")


def _statuses(pilot) -> dict[int, str]:
    rows = pilot.storage._conn.execute("SELECT id, status FROM proposals").fetchall()
    return {r["id"]: r["status"] for r in rows}


def test_approve_mode_notifies_the_pending_trades(tmp_path):
    _, _, _, notifier, pending = _approve_pass(tmp_path)
    events = [e for e in notifier.events if e["type"] == "pending_trades"]
    assert len(events) == 1
    assert events[0]["count"] == len(SYMBOLS)
    assert [ln["id"] for ln in events[0]["lines"]] == [ln["id"] for ln in pending]


def test_approve_submits_only_the_chosen_lines_and_marks_them(tmp_path):
    pilot, broker, _, _, pending = _approve_pass(tmp_path)
    chosen = pending[0]
    assert pilot.approve([chosen["id"]]) == 1
    assert set(broker.positions()) == {chosen["symbol"]}
    status = _statuses(pilot)
    assert status[chosen["id"]] == "submitted"
    assert status[pending[1]["id"]] == "pending"
    assert pilot.approve([chosen["id"]]) == 0              # no double order
    assert broker._order_seq == 1


def test_reject_marks_lines_and_submits_nothing(tmp_path):
    pilot, broker, _, _, pending = _approve_pass(tmp_path)
    assert pilot.reject([ln["id"] for ln in pending]) == len(SYMBOLS)
    assert broker._order_seq == 0
    assert set(_statuses(pilot).values()) == {"rejected"}
    assert pilot.state().pending == 0


def test_a_stale_batch_is_replaced_by_the_next_pass_never_executed(tmp_path):
    pilot, broker, clock, _, first = _approve_pass(tmp_path)
    clock.sleep(300)
    pilot.tick()
    status = _statuses(pilot)
    assert {status[ln["id"]] for ln in first} == {"expired"}
    second = pilot.storage.pending_lines("dry_run")
    assert len(second) == len(SYMBOLS)
    assert not {ln["id"] for ln in first} & {ln["id"] for ln in second}
    assert pilot.approve([ln["id"] for ln in first]) == 0  # expired: never executed
    assert broker._order_seq == 0


def test_a_late_approval_expires_the_batch_instead_of_trading(tmp_path):
    """No pass replaced it (the market closed, the loop stopped), but the
    prices it was sized at are older than one poll: it must not execute."""
    pilot, broker, clock, _, pending = _approve_pass(tmp_path)
    clock.sleep(301)
    assert pilot.approve([ln["id"] for ln in pending]) == 0
    assert broker._order_seq == 0
    assert set(_statuses(pilot).values()) == {"expired"}


def test_switching_off_expires_what_was_waiting(tmp_path):
    pilot, broker, _, _, _ = _approve_pass(tmp_path)
    pilot.set_mode("off")
    assert pilot.state().pending == 0
    assert broker._order_seq == 0


# --- automatic ------------------------------------------------------------------

def test_auto_mode_notifies_each_order(tmp_path):
    pilot, _, _, notifier = build(tmp_path)
    pilot.set_mode("auto")
    pilot.tick()
    orders = [e for e in notifier.events if e["type"] == "order"]
    assert {e["symbol"] for e in orders} == set(SYMBOLS)


def test_daily_loss_halt_sets_mode_off_and_records_the_error(tmp_path, monkeypatch):
    pilot, broker, _, notifier = build(tmp_path)
    pilot.set_mode("auto")
    monkeypatch.setattr(pilot.engine.risk, "daily_loss_tripped", lambda start, now: True)
    assert pilot.run_forever(max_ticks=5) == 1             # the halt ends the loop
    state = pilot.state()
    assert state.mode == "off" and state.last_error == "daily loss halt"
    assert broker._order_seq == 0
    kinds = [e["type"] for e in notifier.events]
    assert "halt" in kinds and "autopilot_off" in kinds


def test_switching_back_on_clears_the_halt_message(tmp_path, monkeypatch):
    pilot, _, _, _ = build(tmp_path)
    pilot.set_mode("auto")
    monkeypatch.setattr(pilot.engine.risk, "daily_loss_tripped", lambda start, now: True)
    pilot.tick()
    assert pilot.set_mode("auto").last_error is None


def test_a_new_trading_day_starts_a_new_loss_session(tmp_path):
    pilot, _, clock, _ = build(tmp_path)
    pilot.set_mode("auto")
    pilot.tick()
    first = pilot.engine._session_start_equity
    assert first is not None
    clock.sleep(300)
    pilot.tick()                                           # same day: same anchor
    assert pilot.engine._session_start_equity == first
    pilot.engine._session_start_equity = 1.0               # mark the old session
    clock.now = OPEN_NOW + timedelta(days=1)
    pilot.tick()                                           # next day: re-anchored
    assert pilot.engine._session_start_equity != 1.0


# --- headless: tradebot run --autopilot -----------------------------------------

def _cli_config(tmp_path, strategy="buy_and_hold") -> str:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "mode: paper\nsymbols: [X, Y]\ntimeframe: 1day\ninitial_cash: 10000\n"
        f"db_path: {tmp_path / 'auto.db'}\n"
        f"strategy:\n  name: {strategy}\n  params: {{}}\n"
    )
    return str(cfg)


def _orders(tmp_path) -> int:
    with Storage(tmp_path / "auto.db") as st:
        return st._conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]


def test_run_autopilot_headless_replay_ticks(tmp_path, capsys):
    rc = main(["run", "--config", _cli_config(tmp_path), "--replay", "--replay-periods", "80",
               "--autopilot", "--mode", "auto", "--iterations", "5"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "[AUTOPILOT] mode=auto account=dry_run" in out
    assert "ticks=5 mode=auto pending=0" in out and "last_error=None" in out
    assert "Dry-run forward-test summary" in out
    assert _orders(tmp_path) >= 2                       # bought X and Y (then rebalanced)


def test_run_autopilot_headless_approve_parks_trades(tmp_path, capsys):
    rc = main(["run", "--config", _cli_config(tmp_path), "--replay", "--replay-periods", "80",
               "--autopilot", "--iterations", "3"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "mode=approve" in out and "ticks=3" in out and "pending=2" in out
    assert _orders(tmp_path) == 0                       # nothing without approval


def test_run_autopilot_headless_replay_ends_when_the_tape_does(tmp_path, capsys):
    rc = main(["run", "--config", _cli_config(tmp_path), "--replay", "--replay-periods", "40",
               "--autopilot", "--mode", "auto"])
    assert rc == 0
    assert "ticks=" in capsys.readouterr().out          # no cap, still terminated


# --- exchange calendars ------------------------------------------------------------

def test_an_autopilot_on_bist_sleeps_until_the_istanbul_open(tmp_path):
    from tradebot.market import get_calendar

    pilot, broker, clock, _ = build(tmp_path, now=WEEKEND)
    pilot = Autopilot(pilot.engine, pilot.storage, poll_seconds=300, clock=clock,
                      sleep=clock.sleep, calendar=get_calendar("bist"))
    pilot.set_mode("auto")
    assert pilot.run_forever(max_ticks=2) == 2
    istanbul_open = datetime(2026, 10, 19, 7, 0, tzinfo=timezone.utc)   # 10:00 UTC+3
    assert clock.slept == [(istanbul_open - WEEKEND).total_seconds()]
    assert pilot.state().last_pass_at == istanbul_open
    assert broker._order_seq == len(SYMBOLS)


def test_the_autopilot_takes_its_calendar_from_the_settings(tmp_path):
    pilot, _, _, _ = build(tmp_path)
    assert pilot.calendar.name == "us_equities"
    pilot.engine.settings.market = "bist"
    again = Autopilot(pilot.engine, pilot.storage, poll_seconds=300)
    assert again.calendar.name == "bist"


def test_a_failed_order_record_never_lets_an_approval_order_twice(tmp_path, monkeypatch):
    """The order reached the broker but recording it failed (database locked):
    the line must already read ``submitted``, so a second tap cannot resend it."""
    import sqlite3

    pilot, broker, _, _, pending = _approve_pass(tmp_path)

    def locked(*a, **k):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(pilot.storage, "record_order", locked)
    chosen = pending[0]
    assert pilot.approve([chosen["id"]]) == 1
    assert _statuses(pilot)[chosen["id"]] == "submitted"
    assert pilot.approve([chosen["id"]]) == 0
    assert broker._order_seq == 1


def test_storage_tolerates_concurrent_writers(tmp_path):
    """The web and the autopilot write the same file: WAL lets readers run
    beside a writer, and a busy writer waits instead of failing at once."""
    with Storage(tmp_path / "t.db") as st:
        assert st._conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert st._conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
