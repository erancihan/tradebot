"""Morning brief: a dry proposal sent once, a set time before each open.

Same harness as test_autopilot: a real Engine over a DryRunBroker and
ReplayData, a fake clock, a sleep that only advances it.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from tradebot.autopilot import Autopilot
from tradebot.autopilot.brief import line_text
from tradebot.advisor.types import ProposalLine
from tradebot.cli import main
from tradebot.config import Settings
from tradebot.storage import Storage

from .test_autopilot import SYMBOLS, _cli_config, build

#: Wednesday 2026-10-14 08:00 New York; the 09:30 open is 13:30 UTC.
BEFORE = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)
BRIEF_AT = datetime(2026, 10, 14, 13, 0, tzinfo=timezone.utc)      # 30 min ahead


def _briefed(tmp_path, now=BEFORE, storage=None):
    pilot, broker, clock, notifier = build(tmp_path, now=now, storage=storage)
    pilot = Autopilot(pilot.engine, pilot.storage, poll_seconds=300, clock=clock,
                      sleep=clock.sleep, notifier=notifier, brief_minutes=30)
    return pilot, broker, clock, notifier


def _briefs(notifier) -> list[dict]:
    return [e for e in notifier.events if e["type"] == "brief"]


def test_morning_brief_fires_once_before_open_with_a_fake_clock(tmp_path):
    pilot, broker, clock, notifier = _briefed(tmp_path)
    assert pilot.state().mode == "off"
    assert pilot.run_forever(max_ticks=2) == 2            # "off" keeps a briefing loop
    assert clock.slept == [(BRIEF_AT - BEFORE).total_seconds()]
    [brief] = _briefs(notifier)
    assert brief["opens_at"] == "2026-10-14T13:30:00+00:00"
    assert brief["text"].splitlines() == [_buy_text(ln) for ln in brief["lines"]]
    assert all(ln.startswith("BUY ") for ln in brief["text"].splitlines())
    assert {ln["symbol"] for ln in brief["lines"]} == set(SYMBOLS)
    # A preview: nothing submitted, nothing parked for approval.
    assert broker._order_seq == 0 and pilot.state().pending == 0

    pilot.tick()                                          # same window: not twice
    clock.now = datetime(2026, 10, 14, 13, 45, tzinfo=timezone.utc)
    pilot.tick()                                          # after the open: not again
    assert len(_briefs(notifier)) == 1


def _buy_text(line: dict) -> str:
    qty = int(line["qty"]) if float(line["qty"]).is_integer() else line["qty"]
    return f"BUY {qty} {line['symbol']} ({line['reason']})"


def test_a_loop_started_after_the_open_waits_for_tomorrows_brief(tmp_path):
    after_open = datetime(2026, 10, 14, 14, 0, tzinfo=timezone.utc)
    pilot, _, clock, notifier = _briefed(tmp_path, now=after_open)
    pilot.run_forever(max_ticks=2)
    tomorrow = datetime(2026, 10, 15, 13, 0, tzinfo=timezone.utc)
    assert clock.slept == [(tomorrow - after_open).total_seconds()]
    [brief] = _briefs(notifier)
    assert brief["opens_at"] == "2026-10-15T13:30:00+00:00"


def test_a_restarted_loop_does_not_resend_the_morning(tmp_path):
    pilot, _, _, notifier = _briefed(tmp_path, now=BRIEF_AT)
    pilot.tick()
    pilot.storage.close()
    again, _, _, again_notes = _briefed(tmp_path, now=BRIEF_AT,
                                        storage=Storage(tmp_path / "t.db"))
    again.tick()
    assert len(_briefs(notifier)) == 1 and _briefs(again_notes) == []


def test_the_brief_rides_alongside_passes_in_auto_mode(tmp_path):
    pilot, broker, clock, notifier = _briefed(tmp_path)
    pilot.set_mode("auto")
    pilot.run_forever(max_ticks=3)       # 12:00 nothing, 13:00 brief, 13:30 pass
    assert len(_briefs(notifier)) == 1
    assert clock.now == datetime(2026, 10, 14, 13, 30, tzinfo=timezone.utc)
    assert broker._order_seq == len(SYMBOLS)


def test_a_failing_brief_is_logged_and_not_retried(tmp_path, monkeypatch):
    pilot, _, _, notifier = _briefed(tmp_path, now=BRIEF_AT)
    monkeypatch.setattr(pilot.engine, "propose", lambda *a, **k: 1 / 0)
    pilot.tick()
    pilot.tick()
    assert _briefs(notifier) == []
    assert pilot.state().last_error is None              # a preview, not a pass


def test_switching_on_wakes_a_briefing_loop_at_once(tmp_path):
    pilot, _, _, _ = build(tmp_path)
    pilot = Autopilot(pilot.engine, pilot.storage, poll_seconds=300, brief_minutes=30)
    pilot.set_mode("auto")
    assert pilot._wake.is_set()          # the default nap returns immediately


def test_line_text_reads_like_an_order():
    def line(action, qty, skipped=False):
        return ProposalLine(symbol="SPY", action=action, target=1, current_qty=0,
                            desired_qty=qty, order_qty=qty, price=1.0, notional=1.0,
                            weight=None, reason="trend up", skipped=skipped)
    assert line_text(line("buy", 3.0)) == "BUY 3 SPY (trend up)"
    assert line_text(line("sell", -1.25)) == "SELL 1.25 SPY (trend up)"
    assert line_text(line("hold", 0.0)) == "HOLD SPY (trend up)"
    assert line_text(line("buy", 0.0, skipped=True)) == "SKIP SPY (trend up)"


def test_brief_minutes_parse_from_the_autopilot_block():
    assert Settings().brief_minutes_before_open is None
    raw = {"autopilot": {"brief_minutes_before_open": 30}}
    assert Settings.from_dict(raw).brief_minutes_before_open == 30


def test_headless_off_mode_needs_a_brief(tmp_path, capsys):
    rc = main(["run", "--config", _cli_config(tmp_path), "--replay", "--replay-periods", "80",
               "--autopilot", "--mode", "off"])
    assert rc == 2 and "brief_minutes_before_open" in capsys.readouterr().out


def test_headless_off_mode_runs_a_briefing_loop(tmp_path, capsys):
    cfg = _cli_config(tmp_path)
    with open(cfg, "a") as fh:
        fh.write("autopilot:\n  brief_minutes_before_open: 30\n")
    rc = main(["run", "--config", cfg, "--replay", "--replay-periods", "80",
               "--autopilot", "--mode", "off", "--iterations", "2"])
    out = capsys.readouterr().out
    assert rc == 0 and "morning brief 30 min" in out and "ticks=2 mode=off" in out


def test_a_negative_lead_is_refused(tmp_path):
    pilot, _, _, _ = build(tmp_path)
    with pytest.raises(ValueError):
        Autopilot(pilot.engine, pilot.storage, poll_seconds=300, brief_minutes=-5)


def test_a_zero_lead_means_no_brief(tmp_path):
    """The Settings form offers 0 as "off"."""
    pilot, _, _, _ = build(tmp_path)
    assert Autopilot(pilot.engine, pilot.storage, poll_seconds=300,
                     brief_minutes=0).brief is None
