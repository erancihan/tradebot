"""Autopilot runner: passes on a timer inside market hours, offline.

Every test drives a real Engine over a DryRunBroker and ReplayData with a fake
clock and a sleep that only advances that clock, so the whole loop (market
hours, scheduling, errors) runs without a network or a wall clock.
"""

from __future__ import annotations

import threading
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from tradebot.autopilot import HALT_ERROR, Autopilot
from tradebot.autopilot.links import ttl_seconds
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
          storage: Storage | None = None, label: str = "dry_run",
          links_persist: bool = False):
    frames = {s: synthetic_ohlcv(periods=80, drift=0.001, volatility=0.01, seed=i)
              for i, s in enumerate(SYMBOLS)}
    data = ReplayData(frames, warmup=60)
    broker = DryRunBroker(data, initial_cash=10_000, slippage_bps=0)
    risk = risk or RiskConfig(max_position_pct=0.4, max_gross_exposure=0.9)
    settings = Settings(mode="paper", symbols=list(SYMBOLS), risk=risk)
    storage = storage or Storage(tmp_path / "t.db")
    notifier = Recorder()
    engine = Engine(settings, broker, data, build_strategy("buy_and_hold", {}),
                    RiskManager(risk), storage, mode_label=label,
                    enforce_live_ack=False, notifier=notifier)
    clock = FakeClock(now)
    pilot = Autopilot(engine, storage, poll_seconds=poll, clock=clock, sleep=clock.sleep,
                      links_persist=links_persist)
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


def test_a_pass_before_the_close_gets_one_wake_after_it(tmp_path):
    late = datetime(2026, 10, 14, 19, 58, tzinfo=timezone.utc)      # 15:58 EDT
    pilot, _, _, _ = build(tmp_path, now=late)
    pilot.set_mode("auto")
    state = pilot.tick()
    assert state.last_pass_at == late
    assert state.next_pass_at == late + timedelta(seconds=300)      # 16:03: closed


def test_the_loop_expires_the_waiting_batch_on_its_wake_after_the_close(tmp_path):
    """The real loop, not a hand-driven tick: the pass at 15:56 parks the
    batch, the scheduled wake at 16:01 finds the market closed, expires it
    and only then sleeps through to the next open."""
    late = datetime(2026, 10, 14, 19, 56, tzinfo=timezone.utc)
    pilot, broker, clock, _ = build(tmp_path, now=late)
    pilot.set_mode("approve")
    pilot.run_forever(max_ticks=2)
    assert clock.slept == [300.0]
    assert _statuses(pilot) and set(_statuses(pilot).values()) == {"expired"}
    assert broker._order_seq == 0
    state = pilot.state()
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


def _spy_proposals(pilot, monkeypatch, change=None) -> list:
    """Record each later pass's proposal, rewritten line by line by ``change``
    (a line, or None to drop it) when given."""
    real, seen = pilot.engine.propose, []

    def propose(*args, **kw):
        proposal = real(*args, **kw)
        if change is not None:
            lines = [change(ln) for ln in proposal.lines]
            proposal = replace(proposal, lines=[ln for ln in lines if ln is not None])
        seen.append(proposal)
        return proposal

    monkeypatch.setattr(pilot.engine, "propose", propose)
    return seen


def _one_more_share(line):
    """The same trade, re-sized: the prices moved since the last pass."""
    price, qty = line.price + 1.0, line.order_qty + 1
    return replace(line, price=price, order_qty=qty, desired_qty=line.desired_qty + 1,
                   notional=abs(qty) * price)


def _pushes(notifier) -> list[dict]:
    return [e for e in notifier.events if e["type"] == "pending_trades"]


def test_an_unchanged_proposal_keeps_the_pending_batch(tmp_path, monkeypatch):
    pilot, broker, clock, _, first = _approve_pass(tmp_path)
    seen = _spy_proposals(pilot, monkeypatch, _one_more_share)
    clock.sleep(300)
    pilot.tick()
    second = pilot.storage.pending_lines("dry_run")
    assert [ln["id"] for ln in second] == [ln["id"] for ln in first]
    assert {ln["batch_id"] for ln in second} == {first[0]["batch_id"]}
    assert "expired" not in _statuses(pilot).values()
    newer = {ln.symbol: ln for ln in seen[0].lines}
    for line in second:
        fresh = newer[line["symbol"]]
        assert (line["price"], line["order_qty"]) == (fresh.price, fresh.order_qty)
        assert line["created_at"] == clock.now.isoformat()
    assert all(b["order_qty"] == a["order_qty"] + 1 for a, b in zip(first, second))
    head = pilot.storage.latest_proposal("dry_run")
    assert head["id"] == first[0]["batch_id"] and head["created_at"] == clock.now.isoformat()
    assert broker._order_seq == 0


def test_a_rejected_line_is_not_asked_again_while_the_proposal_holds(tmp_path):
    pilot, _, clock, notifier, first = _approve_pass(tmp_path)
    kept, dropped = first
    assert pilot.reject([dropped["id"]]) == 1
    clock.sleep(300)
    pilot.tick()
    status = _statuses(pilot)
    assert status[dropped["id"]] == "rejected" and status[kept["id"]] == "pending"
    assert [ln["id"] for ln in pilot.storage.pending_lines("dry_run")] == [kept["id"]]
    assert len(_pushes(notifier)) == 1


def test_a_changed_proposal_replaces_the_batch(tmp_path, monkeypatch):
    pilot, broker, clock, notifier, first = _approve_pass(tmp_path)
    _spy_proposals(pilot, monkeypatch, lambda ln: ln if ln.symbol == SYMBOLS[0] else None)
    clock.sleep(300)
    pilot.tick()
    status = _statuses(pilot)
    assert {status[ln["id"]] for ln in first} == {"expired"}
    second = pilot.storage.pending_lines("dry_run")
    assert [ln["symbol"] for ln in second] == [SYMBOLS[0]]
    assert second[0]["batch_id"] != first[0]["batch_id"]
    pushes = _pushes(notifier)
    assert [p["batch_id"] for p in pushes] == [first[0]["batch_id"], second[0]["batch_id"]]
    assert pilot.approve([ln["id"] for ln in first]) == 0  # expired: never executed
    assert broker._order_seq == 0


def test_only_a_new_batch_or_a_due_reminder_is_announced(tmp_path):
    pilot, _, clock, notifier, first = _approve_pass(tmp_path)
    for _ in range(2):
        clock.sleep(300)
        pilot.tick()                                        # t+5m, t+10m: quiet
    assert len(_pushes(notifier)) == 1
    clock.now = OPEN_NOW + timedelta(seconds=ttl_seconds(pilot.poll_seconds))
    pilot.tick()                                            # a link lifetime later
    pushes = _pushes(notifier)
    assert len(pushes) == 2
    assert {p["batch_id"] for p in pushes} == {first[0]["batch_id"]}
    clock.sleep(300)
    pilot.tick()
    assert len(_pushes(notifier)) == 2                      # the reminder resets the wait


def _half_again(line):
    """The same trade grown well past what the push said (equity jumped)."""
    qty = line.order_qty * 1.5
    return replace(line, order_qty=qty, desired_qty=line.desired_qty * 1.5,
                   notional=abs(qty) * line.price)


def test_a_carried_line_grown_past_the_push_is_pushed_again(tmp_path, monkeypatch):
    """An approval must mean what the phone showed: a refresh that grows a
    line by more than the tolerance pushes the batch again at once."""
    pilot, _, clock, notifier, first = _approve_pass(tmp_path)
    _spy_proposals(pilot, monkeypatch, _one_more_share)
    clock.sleep(300)
    pilot.tick()                                            # one share more: quiet
    assert len(_pushes(notifier)) == 1
    _spy_proposals(pilot, monkeypatch, _half_again)
    clock.sleep(300)
    pilot.tick()                                            # half again: pushed
    pushes = _pushes(notifier)
    assert len(pushes) == 2
    assert pushes[-1]["batch_id"] == first[0]["batch_id"]
    assert pushes[-1]["lines"][0]["qty"] > first[0]["order_qty"]
    clock.sleep(300)
    pilot.tick()                                            # same size again: quiet
    assert len(_pushes(notifier)) == 2


def _shown(lines) -> dict[int, float]:
    """What a page (or a push) showed: ``{line id: notional}``."""
    return {ln["id"]: ln["notional"] for ln in lines}


def test_approval_after_a_refresh_submits_the_latest_quantity_within_what_was_shown(
        tmp_path, monkeypatch):
    """A refresh within ``GROWTH_TOLERANCE`` of what the approver saw submits
    the refreshed size (the prices moved a little; the trade is the same)."""
    pilot, broker, clock, _, first = _approve_pass(tmp_path)
    seen = _spy_proposals(pilot, monkeypatch, _one_more_share)
    clock.sleep(300)
    pilot.tick()
    clock.sleep(120)                                        # within one poll of the refresh
    assert pilot.approve([ln["id"] for ln in first], _shown(first)) == len(SYMBOLS)
    held = {sym: pos.qty for sym, pos in broker.positions().items()}
    assert held == {ln.symbol: ln.order_qty for ln in seen[0].lines}
    assert held == {ln["symbol"]: ln["order_qty"] + 1 for ln in first}


def test_approval_refuses_a_line_grown_past_what_the_page_showed(tmp_path, monkeypatch):
    """The page showed the first sizes; a refresh grew them by half: the tap
    must not buy the new size. The lines stay pending for the next look."""
    pilot, broker, clock, _, first = _approve_pass(tmp_path)
    _spy_proposals(pilot, monkeypatch, _half_again)
    clock.sleep(300)
    pilot.tick()
    result = pilot.approve_detail([ln["id"] for ln in first], _shown(first))
    assert result.submitted == 0 and sorted(result.held) == sorted(SYMBOLS)
    assert broker._order_seq == 0
    again = pilot.storage.pending_lines("dry_run")
    assert pilot.approve([ln["id"] for ln in again], _shown(again)) == len(SYMBOLS)


def test_an_older_push_cannot_approve_a_line_grown_past_what_it_showed(
        tmp_path, monkeypatch):
    """Push 1 said BUY n; a refresh grew it 1.5x and push 2 said so. Push 1's
    Approve (still unexpired) must not buy 1.5n: it is held to push 1's size,
    and push 2's button, which showed the new size, buys it."""
    pilot, broker, clock, notifier, first = _approve_pass(tmp_path)
    batch = first[0]["batch_id"]
    _spy_proposals(pilot, monkeypatch, _half_again)
    clock.sleep(300)
    pilot.tick()
    old, new = (p["link_exp"] for p in _pushes(notifier))
    assert old != new
    stale = pilot.act_on_batch(batch, "approve", old)
    assert stale.submitted == 0 and sorted(stale.held) == sorted(SYMBOLS)
    assert broker._order_seq == 0 and len(pilot.storage.pending_lines("dry_run")) == 2
    assert pilot.act_on_batch(batch, "approve", new).submitted == len(SYMBOLS)
    shown = {ln["symbol"]: ln["qty"] for ln in _pushes(notifier)[-1]["lines"]}
    assert {s: p.qty for s, p in broker.positions().items()} == shown


def test_a_push_not_on_record_approves_nothing(tmp_path):
    pilot, broker, _, _, first = _approve_pass(tmp_path)
    result = pilot.act_on_batch(first[0]["batch_id"], "approve", 123)
    assert result.submitted == 0 and broker._order_seq == 0


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


@pytest.mark.parametrize("token, lasting", [("s3cret", True), (None, False)])
def test_the_headless_pilots_links_persist_with_the_token(tmp_path, monkeypatch,
                                                          token, lasting):
    """The CLI signs with ``env_secret``: stable exactly when the token is set."""
    import tradebot.autopilot as autopilot_pkg

    built: list = []

    class Spy(Autopilot):
        def __init__(self, *args, **kw):
            super().__init__(*args, **kw)
            built.append(self)

    monkeypatch.setattr(autopilot_pkg, "Autopilot", Spy)
    if token is None:
        monkeypatch.delenv("TRADEBOT_WEB_TOKEN", raising=False)
    else:
        monkeypatch.setenv("TRADEBOT_WEB_TOKEN", token)
    assert main(["run", "--config", _cli_config(tmp_path), "--replay", "--replay-periods",
                 "80", "--autopilot", "--iterations", "1"]) == 0
    assert [p.links_persist for p in built] == [lasting]


class _Pushed:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_a_replay_autopilot_push_has_only_the_open_button(tmp_path, capsys, monkeypatch):
    """Links are paper-only: the web cannot act on a replay's batch, so the
    headless replay's push carries "Open" and no Approve or Skip."""
    pushes: list = []
    monkeypatch.setattr("tradebot.notify.urllib.request.urlopen",
                        lambda req, timeout=None: (pushes.append(req), _Pushed())[1])
    cfg = _cli_config(tmp_path)
    with open(cfg, "a") as fh:
        fh.write("notify:\n  ntfy_topic: t0pic\n  ntfy_server: http://127.0.0.1:9\n"
                 "  public_url: http://192.168.1.20:8000\n")
    assert main(["run", "--config", cfg, "--replay", "--replay-periods", "80",
                 "--autopilot", "--iterations", "2"]) == 0
    actions = {p.get_header("Actions") for p in pushes if p.get_header("Actions")}
    assert actions == {'view, Open, "http://192.168.1.20:8000/autopilot"'}


def test_a_live_pilots_pending_push_carries_its_mode_and_no_approve(tmp_path, monkeypatch):
    """End to end from ``Autopilot._notify``: the header's paper-only check
    reads the event's ``mode``, so the runner must stamp it. Armed with a
    signer on purpose: the event alone must keep Approve off a live push."""
    from tradebot.autopilot.links import link_secret, link_signer
    from tradebot.notify import NtfyNotifier

    pushes: list = []
    monkeypatch.setattr("tradebot.notify.urllib.request.urlopen",
                        lambda req, timeout=None: (pushes.append(req), _Pushed())[1])
    events: list = []

    class Seen(NtfyNotifier):
        def send(self, event: dict) -> None:
            events.append(event)
            super().send(event)

    pilot, _, _, _ = build(tmp_path, label="live")
    pilot.notifier = Seen("t0pic", server="http://127.0.0.1:9",
                          public_url="http://192.168.1.20:8000",
                          link_signer=link_signer(link_secret("t"), "live", 300))
    pilot.set_mode("approve")
    pilot.tick()
    (event,) = [e for e in events if e["type"] == "pending_trades"]
    assert event["mode"] == "live"
    (push,) = [p for p in pushes if p.get_header("Title") == "tradebot: pending_trades"]
    assert push.get_header("Actions") == 'view, Open, "http://192.168.1.20:8000/autopilot"'


def test_the_cli_arms_links_only_for_paper(monkeypatch):
    from tradebot.cli.autopilot import _linked_notifier

    settings = Settings.from_dict({"notify": {"ntfy_topic": "t",
                                              "public_url": "http://192.168.1.20:8000"}})
    monkeypatch.setenv("TRADEBOT_WEB_TOKEN", "s3cret")
    assert _linked_notifier(settings, "paper").notifiers[1].link_signer is not None
    for account in ("dry_run", "live"):
        assert _linked_notifier(settings, account).notifiers[1].link_signer is None
    # Without the token this process's key is random: no web process could
    # verify its links, so a paper push carries just "Open".
    monkeypatch.delenv("TRADEBOT_WEB_TOKEN")
    assert _linked_notifier(settings, "paper").notifiers[1].link_signer is None


def _down_then_up(path, bars=60) -> str:
    """One daily bar per day: 30 bars falling 1% each, then 30 rising 1% each."""
    import pandas as pd

    index = pd.date_range("2024-01-02 21:00", periods=bars, freq="D", tz="UTC")
    closes, price = [], 100.0
    for i in range(bars):
        price *= 0.99 if i < bars // 2 else 1.01
        closes.append(price)
    opens = [100.0, *closes[:-1]]
    frame = pd.DataFrame({"timestamp": index, "open": opens, "close": closes,
                          "high": [max(o, c) for o, c in zip(opens, closes)],
                          "low": [min(o, c) for o, c in zip(opens, closes)],
                          "volume": 1e6})
    frame.to_csv(path, index=False)
    return str(path)


def test_a_replay_autopilot_takes_one_session_day_per_bar(tmp_path, capsys):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "mode: paper\nsymbols: [X]\ntimeframe: 1day\ninitial_cash: 10000\n"
        f"db_path: {tmp_path / 'auto.db'}\n"
        "strategy:\n  name: buy_and_hold\n  params: {}\n"
        "risk:\n  max_position_pct: 1.0\n  max_daily_loss_pct: 0.03\n")
    tape = _down_then_up(tmp_path / "tape.csv")
    rc = main(["run", "--config", str(cfg), "--replay-csv", tape,
               "--autopilot", "--mode", "auto"])
    out = capsys.readouterr().out
    assert rc == 0
    # A 1% bar never breaches a 3% daily limit; a 26% fall over 30 sessions
    # is not a daily loss, so the run ticks to the end of the tape.
    assert "ticks=58 mode=auto" in out and "last_error=None" in out


def test_the_replay_clock_follows_the_bars():
    from tradebot.autopilot.schedule import session_day
    from tradebot.cli.autopilot import _ReplayClock

    df = synthetic_ohlcv(periods=5, start="2024-03-04", freq="B")
    data = ReplayData({"X": df}, warmup=2)
    clock = _ReplayClock(data, speed=0)
    assert clock() == df.index[1]
    clock.sleep(300)
    assert clock() == df.index[2]
    assert session_day(clock(), timezone.utc) == df.index[2].date()


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


# --- the daily-loss anchor survives a rebuild ------------------------------------

def _restarted(tmp_path, *, now, equity):
    """A second runner on the same database (a restart, or a Settings save
    that rebuilt the engine) whose account now stands at ``equity``."""
    risk = RiskConfig(max_position_pct=0.4, max_gross_exposure=0.9, max_daily_loss_pct=0.03)
    pilot, broker, _, _ = build(tmp_path, now=now, risk=risk)
    broker.portfolio.cash = equity
    return pilot


def test_a_restart_keeps_the_days_loss_anchor(tmp_path):
    first, _, _, _ = build(tmp_path)
    first.set_mode("auto")
    first.tick()
    assert float(first.storage.autopilot_values("dry_run")["session_start_equity"]) == 10_000

    pilot = _restarted(tmp_path, now=OPEN_NOW + timedelta(hours=1), equity=9_500)
    state = pilot.tick()                       # down 5% on the day: the breaker trips
    assert state.mode == "off" and state.last_error == HALT_ERROR


def test_a_new_day_re_anchors_after_a_restart(tmp_path):
    first, _, _, _ = build(tmp_path)
    first.set_mode("auto")
    first.tick()

    pilot = _restarted(tmp_path, now=OPEN_NOW + timedelta(days=1), equity=9_500)
    assert pilot.tick().mode == "auto"         # yesterday's anchor no longer applies
    assert float(pilot.storage.autopilot_values("dry_run")["session_start_equity"]) == 9_500


def test_concurrent_starts_run_one_loop(tmp_path, monkeypatch):
    """Two mode taps at once must not both see "no thread" and start two loops."""
    import time

    import tradebot.autopilot.runner as runner

    class SlowStart(threading.Thread):       # widens the check-then-start window
        def start(self):
            time.sleep(0.05)
            super().start()

    monkeypatch.setattr(runner.threading, "Thread", SlowStart)
    shared = Storage(tmp_path / "t.db", check_same_thread=False)
    pilot, _, _, _ = build(tmp_path, now=WEEKEND, storage=shared)
    pilot._sleep = pilot._nap                 # a real nap, so the loop stays up
    pilot.set_mode("auto")
    gate = threading.Barrier(2)
    started: list[bool] = []

    def tap():
        gate.wait()
        started.append(pilot.start())

    taps = [threading.Thread(target=tap) for _ in range(2)]
    for t in taps:
        t.start()
    for t in taps:
        t.join(5)
    try:
        assert sorted(started) == [False, True]
    finally:
        pilot.stop()


def _order_times(pilot) -> list[str]:
    rows = pilot.storage._conn.execute("SELECT ts FROM orders ORDER BY id").fetchall()
    return [r[0] for r in rows]


def test_orders_carry_the_pass_clock_not_wall_time(tmp_path):
    """History merges orders with batches by time: in a replay both must read
    the replay clock. An approval is stamped with the clock at approval."""
    past = OPEN_NOW - timedelta(days=7)                # a Wednesday session
    pilot, _, clock, _ = build(tmp_path, now=past)
    pilot.set_mode("auto")
    pilot.tick()
    assert _order_times(pilot) == [past.isoformat()] * len(SYMBOLS)

    (tmp_path / "approve").mkdir()
    pilot, _, clock, _ = build(tmp_path / "approve", now=past)
    pilot.set_mode("approve")
    pilot.tick()
    clock.now = past + timedelta(seconds=60)          # inside the poll window
    pending = pilot.storage.pending_lines(pilot.account)
    assert pilot.approve([pending[0]["id"]]) == 1
    assert _order_times(pilot) == [clock.now.isoformat()]


# --- a waiting batch: rejections, restarts, Today, and the expiry points -------

def test_rejecting_every_line_holds_until_the_proposal_changes(tmp_path):
    """Skip on the phone rejects the whole batch; the same trades on the next
    pass are the same question, already answered: no new batch, no push."""
    pilot, broker, clock, notifier, first = _approve_pass(tmp_path)
    assert pilot.reject([ln["id"] for ln in first]) == len(SYMBOLS)
    clock.sleep(300)
    pilot.tick()
    assert pilot.storage.pending_lines("dry_run") == []
    assert set(_statuses(pilot).values()) == {"rejected"}
    batches = pilot.storage._conn.execute("SELECT COUNT(*) FROM proposal_batches").fetchone()
    assert batches[0] == 1
    assert len(_pushes(notifier)) == 1
    assert broker._order_seq == 0


def test_a_rejection_ends_with_the_trading_day(tmp_path):
    pilot, _, clock, notifier, first = _approve_pass(tmp_path)
    pilot.reject([ln["id"] for ln in first])
    clock.now = OPEN_NOW + timedelta(days=1)            # Thursday's session
    pilot.tick()
    fresh = pilot.storage.pending_lines("dry_run")
    assert {ln["symbol"] for ln in fresh} == set(SYMBOLS)
    assert {ln["batch_id"] for ln in fresh} != {first[0]["batch_id"]}
    pushes = _pushes(notifier)
    assert len(pushes) == 2 and pushes[-1]["batch_id"] == fresh[0]["batch_id"]


def test_a_restarted_pilot_pushes_its_carried_batch_once(tmp_path):
    """The links the old process signed may be dead (a per-process key), so
    the first pass after a restart pushes the carried batch again."""
    first, _, _, _, parked = _approve_pass(tmp_path)
    pilot, _, _, notifier = build(tmp_path, now=OPEN_NOW + timedelta(seconds=300),
                                  storage=first.storage)
    pilot.tick()
    pushes = _pushes(notifier)
    assert [p["batch_id"] for p in pushes] == [parked[0]["batch_id"]]
    pilot.clock.sleep(300)
    pilot.tick()
    assert len(_pushes(notifier)) == 1                  # then quiet again


def _restarted_with_lasting_links(tmp_path):
    """A restart whose link key survives it (TRADEBOT_WEB_TOKEN set)."""
    first, _, _, _, parked = _approve_pass(tmp_path)
    pilot, _, clock, notifier = build(tmp_path, now=OPEN_NOW + timedelta(seconds=300),
                                      storage=first.storage, links_persist=True)
    return pilot, clock, notifier, parked


def test_a_restart_with_lasting_links_does_not_push_the_batch_again(tmp_path):
    """The push already on the phone still has working buttons, so a restart
    (six in an hour on the soak) must not push the same batch again; the
    reminder keeps its cadence from the stored push time."""
    pilot, clock, notifier, parked = _restarted_with_lasting_links(tmp_path)
    pilot.tick()
    assert _pushes(notifier) == []
    assert pilot.storage.pending_lines("dry_run")[0]["batch_id"] == parked[0]["batch_id"]
    clock.now = OPEN_NOW + timedelta(seconds=ttl_seconds(pilot.poll_seconds) - 1)
    pilot.tick()
    assert _pushes(notifier) == []                      # not yet a link lifetime
    clock.now = OPEN_NOW + timedelta(seconds=ttl_seconds(pilot.poll_seconds))
    pilot.tick()
    assert [p["batch_id"] for p in _pushes(notifier)] == [parked[0]["batch_id"]]
    clock.sleep(300)
    pilot.tick()
    assert len(_pushes(notifier)) == 1                  # the reminder resets the wait


def test_a_restart_with_lasting_links_still_pushes_a_grown_line(tmp_path, monkeypatch):
    pilot, clock, notifier, parked = _restarted_with_lasting_links(tmp_path)
    pilot.tick()
    assert _pushes(notifier) == []
    _spy_proposals(pilot, monkeypatch, _half_again)
    clock.sleep(300)
    pilot.tick()                                        # grown from the stored push
    pushes = _pushes(notifier)
    assert [p["batch_id"] for p in pushes] == [parked[0]["batch_id"]]
    assert pushes[0]["lines"][0]["qty"] > parked[0]["order_qty"]


def test_today_shows_the_carried_batch_over_an_older_suggestion(tmp_path):
    from tradebot.web.repository.proposals import latest_proposal

    pilot, _, clock, _, first = _approve_pass(tmp_path)
    manual = pilot.engine.propose(10_000, 10_000, now=OPEN_NOW + timedelta(seconds=60))
    pilot.storage.record_proposal(manual, "dry_run")    # a Today refresh in between
    clock.sleep(300)
    pilot.tick()
    for head in (pilot.storage.latest_proposal("dry_run"),
                 latest_proposal(str(tmp_path / "t.db"), "dry_run")):
        assert head["id"] == first[0]["batch_id"]
        assert head["created_at"] == clock.now.isoformat()


def test_a_carried_batch_refreshes_its_hold_lines(tmp_path, monkeypatch):
    pilot, _, _, _ = build(tmp_path)
    real, prices = pilot.engine.propose, iter([10.0, 11.0])

    def propose(*args, **kw):
        proposal = real(*args, **kw)
        hold = replace(proposal.lines[0], symbol="C", action="hold", target=0,
                       order_qty=0.0, desired_qty=0.0, notional=0.0, price=next(prices))
        return replace(proposal, lines=[*proposal.lines, hold])

    monkeypatch.setattr(pilot.engine, "propose", propose)
    pilot.set_mode("approve")
    pilot.tick()
    pilot.clock.sleep(300)
    pilot.tick()
    head = pilot.storage.latest_proposal("dry_run")
    (hold,) = [ln for ln in head["lines"] if ln["symbol"] == "C"]
    assert hold["status"] == "suggested" and hold["price"] == 11.0
    assert hold["created_at"] == pilot.clock.now.isoformat()


def test_a_failed_approve_pass_expires_the_waiting_batch(tmp_path, monkeypatch):
    pilot, broker, clock, _, _ = _approve_pass(tmp_path)

    def explode(**kw):
        raise RuntimeError("broker unreachable")

    monkeypatch.setattr(pilot.engine, "step", explode)
    clock.sleep(300)
    pilot.tick()
    assert set(_statuses(pilot).values()) == {"expired"}
    assert broker._order_seq == 0


def test_the_first_closed_tick_expires_the_waiting_batch(tmp_path):
    """After the close no pass runs, so the tick itself must retire the batch:
    Today would otherwise show it all night, and an approval queued after the
    close would ride to the open at unknown prices."""
    pilot, broker, clock, _, _ = _approve_pass(tmp_path)
    clock.now = datetime(2026, 10, 14, 20, 1, tzinfo=timezone.utc)    # 16:01 EDT
    state = pilot.tick()
    assert set(_statuses(pilot).values()) == {"expired"}
    assert broker._order_seq == 0
    assert state.last_pass_at == OPEN_NOW                             # no pass ran
    assert state.next_pass_at == datetime(2026, 10, 15, 13, 30, tzinfo=timezone.utc)


def test_a_broker_closed_approve_pass_expires_the_waiting_batch(tmp_path, monkeypatch):
    from tradebot.engine.pending import PassOutcome

    pilot, broker, clock, _, _ = _approve_pass(tmp_path)
    monkeypatch.setattr(pilot.engine, "step", lambda **kw: PassOutcome(market_closed=True))
    clock.sleep(300)
    pilot.tick()
    assert set(_statuses(pilot).values()) == {"expired"}
    assert broker._order_seq == 0


# --- approval safety: positions, double sends, the close, holds, failures ------

def _sell_a_to_flat(held: float):
    def change(ln):
        if ln.symbol != "A":
            return None
        return replace(ln, action="sell", target=0, desired_qty=0.0, current_qty=held,
                       order_qty=-held, notional=held * ln.price, reason="off the list")
    return change


def test_an_approved_exit_whose_position_is_gone_expires_instead_of_shorting(
        tmp_path, monkeypatch):
    """A sell-to-flat line was parked, then A was sold by hand (or a stop
    fired): approving the stored "sell N" against 0 would open a short."""
    from tradebot.models import Order, Side

    pilot, broker, clock, _ = build(tmp_path)
    pilot.set_mode("auto")
    pilot.tick()
    held = broker.position("A").qty
    assert held > 0
    _spy_proposals(pilot, monkeypatch, _sell_a_to_flat(held))
    pilot.set_mode("approve")
    clock.sleep(300)
    pilot.tick()
    (line,) = pilot.storage.pending_lines("dry_run")
    broker.submit(Order(symbol="A", qty=held, side=Side.SELL, created_at=clock.now))
    clock.sleep(60)
    result = pilot.approve_detail([line["id"]])
    assert result.submitted == 0 and result.moved == ["A"]
    assert broker.position("A").qty == 0                  # flat, never short
    assert _statuses(pilot)[line["id"]] == "expired"


def test_an_approved_entry_after_the_position_changed_expires(tmp_path):
    """The same check guards a double buy: the stored buy was sized against
    nothing held, and the name was bought since."""
    from tradebot.models import Order, Side

    pilot, broker, clock, _, first = _approve_pass(tmp_path)
    line = first[0]
    broker.submit(Order(symbol=line["symbol"], qty=line["order_qty"], side=Side.BUY,
                        created_at=clock.now))
    assert pilot.approve([ln["id"] for ln in first]) == 1          # the other one
    assert broker.position(line["symbol"]).qty == line["order_qty"]   # not doubled
    assert _statuses(pilot)[line["id"]] == "expired"


def test_a_failed_submitted_mark_never_lets_a_second_tap_order_again(tmp_path, monkeypatch):
    """The order is out but marking the line ``submitted`` failed (database
    locked): the line must not be sent again, and the mark is retried."""
    import sqlite3

    pilot, broker, clock, _, first = _approve_pass(tmp_path)
    real = pilot.storage.set_line_status

    def flaky(ids, status):
        if status == "submitted":
            raise sqlite3.OperationalError("database is locked")
        return real(ids, status)

    monkeypatch.setattr(pilot.storage, "set_line_status", flaky)
    line = first[0]
    assert pilot.approve([line["id"]]) == 1
    clock.sleep(10)
    assert pilot.approve([line["id"]]) == 0                     # never twice
    assert broker.position(line["symbol"]).qty == line["order_qty"]
    assert pilot.state().pending == 2                           # the mark is still due
    monkeypatch.setattr(pilot.storage, "set_line_status", real)  # the lock is gone
    clock.sleep(290)
    pilot.tick()
    assert _statuses(pilot)[line["id"]] == "submitted"
    assert broker._order_seq == 1


def test_an_approval_after_the_close_expires_instead_of_queueing(tmp_path):
    """Approved at 16:01:30, before the wake after the close: a DAY market
    order would queue for the next open at prices nobody saw."""
    late = datetime(2026, 10, 14, 19, 58, tzinfo=timezone.utc)      # 15:58 EDT
    pilot, broker, clock, _, first = _approve_pass(tmp_path, now=late)
    clock.now = datetime(2026, 10, 14, 20, 1, 30, tzinfo=timezone.utc)
    result = pilot.approve_detail([ln["id"] for ln in first])
    assert result.closed and result.submitted == 0
    assert broker._order_seq == 0
    assert set(_statuses(pilot).values()) == {"expired"}


def _holds_then(flag: dict):
    def change(ln):
        if flag["hold"]:
            return replace(ln, action="hold", order_qty=0.0, notional=0.0,
                           desired_qty=ln.current_qty)
        return ln
    return change


def test_a_skip_does_not_outlive_a_hold_interlude(tmp_path, monkeypatch):
    """Skip at 10:00, holds at 10:05, the same buys at 10:10: the holds were
    a different answer, so the buys are a new question, asked and pushed."""
    pilot, _, clock, notifier, first = _approve_pass(tmp_path)
    pilot.reject([ln["id"] for ln in first])
    flag = {"hold": True}
    _spy_proposals(pilot, monkeypatch, _holds_then(flag))
    clock.sleep(300)
    pilot.tick()
    flag["hold"] = False
    clock.sleep(300)
    pilot.tick()
    fresh = pilot.storage.pending_lines("dry_run")
    assert {ln["symbol"] for ln in fresh} == set(SYMBOLS)
    assert {ln["batch_id"] for ln in fresh} != {first[0]["batch_id"]}
    assert _pushes(notifier)[-1]["batch_id"] == fresh[0]["batch_id"]


def test_repeated_all_hold_passes_refresh_one_batch(tmp_path, monkeypatch):
    """A quiet market answers "hold" every poll: one History batch for it,
    refreshed in place, not one per poll."""
    pilot, _, clock, _ = build(tmp_path)
    _spy_proposals(pilot, monkeypatch, _holds_then({"hold": True}))
    pilot.set_mode("approve")
    for _ in range(3):
        pilot.tick()
        clock.sleep(300)
    rows = pilot.storage._conn.execute("SELECT id, created_at FROM proposal_batches").fetchall()
    assert len(rows) == 1
    assert rows[0]["created_at"] == (clock.now - timedelta(seconds=300)).isoformat()


def _refuse(order):
    raise RuntimeError("insufficient buying power")


def test_an_auto_pass_whose_orders_fail_says_so(tmp_path, monkeypatch):
    pilot, broker, _, notifier = build(tmp_path)
    monkeypatch.setattr(broker, "submit", _refuse)
    pilot.set_mode("auto")
    state = pilot.tick()
    assert state.last_error.startswith("order failed: A (RuntimeError: insufficient")
    assert "B (" in state.last_error
    (event,) = [e for e in notifier.events if e["type"] == "order_failed"]
    assert event["symbols"] == ["A", "B"] and event["mode"] == "dry_run"


def test_an_approval_whose_orders_fail_says_so_and_leaves_them_pending(
        tmp_path, monkeypatch):
    pilot, broker, _, notifier, first = _approve_pass(tmp_path)
    monkeypatch.setattr(broker, "submit", _refuse)
    result = pilot.act_on_batch(first[0]["batch_id"], "approve",
                                _pushes(notifier)[0]["link_exp"])
    assert result.submitted == 0 and [s for s, _ in result.failed] == ["A", "B"]
    assert len(pilot.storage.pending_lines("dry_run")) == len(SYMBOLS)
    assert "insufficient buying power" in pilot.state().last_error
    assert [e["type"] for e in notifier.events].count("order_failed") == 1


def test_a_stop_mid_pass_parks_nothing_and_a_stopped_pilot_starts_no_pass(
        tmp_path, monkeypatch):
    """A reset stops the runner while its pass runs: a newer runner may own
    the account by the time the pass returns, so it parks nothing, and a
    stopped runner starts no new pass."""
    pilot, _, _, notifier = build(tmp_path)
    pilot.set_mode("approve")
    real = pilot.engine.step

    def stopped_during(**kw):
        out = real(**kw)
        pilot.stop(timeout=0)
        return out

    monkeypatch.setattr(pilot.engine, "step", stopped_during)
    pilot.tick()
    assert pilot.storage.pending_lines("dry_run") == [] and _pushes(notifier) == []
    monkeypatch.setattr(pilot.engine, "step", lambda **kw: pytest.fail("a new pass ran"))
    pilot.tick()


def test_a_reminder_comes_before_the_pushed_links_die_after_a_poll_change(tmp_path):
    """The push's links expire at its own ttl. A poll raised since (a Settings
    save, the key lasting) must not stretch the reminder past that."""
    pilot, clock, notifier, parked = _restarted_with_lasting_links(tmp_path)
    pilot.poll_seconds = 3600                          # ttl 7200, the push's was 1800
    clock.now = OPEN_NOW + timedelta(seconds=ttl_seconds(300))
    pilot.tick()
    pushes = _pushes(notifier)
    assert [p["batch_id"] for p in pushes] == [parked[0]["batch_id"]]
