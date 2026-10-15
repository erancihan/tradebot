"""`tradebot run --autopilot`: the web's Autopilot runner, headless.

The engine is built exactly as `run` builds it (replay, dry-run or paper; a
live config still needs the confirmation latch), then the same ``Autopilot``
the web process owns drives it. A replay has no wall clock, so it gets a
simulated one: every bar is "open", each sleep advances one bar, and the
clock reads the newest bar's timestamp.
"""

from __future__ import annotations

import argparse
import time
from datetime import datetime

from .common import _resolve_universe
from .dryrun import _build_dry_engine, _print_dryrun_summary


class _ReplayClock:
    """Simulated time for a replay: sleeping advances one bar, and "now" is
    that bar's timestamp.

    The clock follows the bars, not the requested sleep: a 300 s poll on a
    daily tape would otherwise put ~288 bars in one session day, so the
    daily-loss anchor would never reset and a slow fall would halt the run.
    """

    def __init__(self, data, speed: float) -> None:
        self.data, self.speed = data, speed
        self.now: datetime = data.timestamp.to_pydatetime()
        self.pilot = None

    def __call__(self) -> datetime:
        return self.now

    def sleep(self, seconds: float) -> None:
        if not self.data.has_next():
            self.pilot.stop(timeout=0)            # the tape ran out: end the run
            return
        self.data.advance()
        self.now = self.data.timestamp.to_pydatetime()
        if self.speed:
            time.sleep(self.speed)


def run_autopilot(settings, args: argparse.Namespace) -> int:
    from ..autopilot import Autopilot
    from ..market import get_calendar

    if args.mode == "off" and not settings.brief_minutes_before_open:
        print("--mode off only sends the morning brief; set "
              "autopilot.brief_minutes_before_open in the config.")
        return 2
    built = _build(settings, args)
    if built is None:
        return 2
    engine, data, broker, replay = built
    extra: dict = {}
    if replay:
        clock = _ReplayClock(data, args.speed)
        extra = dict(clock=clock, sleep=clock.sleep, is_open=lambda now: True)
    if settings.notify_public_url:
        extra["notifier"] = _linked_notifier(settings, engine.mode)
    # Its own state scope: the web's stored mode is what the next
    # `tradebot-web` start resumes, so a headless run must never write it.
    pilot = Autopilot(engine, engine.storage, poll_seconds=settings.poll_seconds,
                      calendar=get_calendar(settings.market),
                      scope=f"cli_{engine.mode}", **extra)
    if replay:
        clock.pilot = pilot
    pilot.set_mode(args.mode, expire_pending=False)
    print(f"[AUTOPILOT] mode={args.mode} account={engine.mode} on {settings.symbols} "
          f"with {engine.strategy.name}; every {settings.poll_seconds}s in {settings.market} hours.")
    if pilot.brief is not None:
        print(f"[AUTOPILOT] morning brief {settings.brief_minutes_before_open} min "
              f"before each {settings.market} open.")
    try:
        ticks = pilot.run_forever(max_ticks=1 if args.once else args.iterations)
    except KeyboardInterrupt:
        ticks = None
        print("\n[AUTOPILOT] Interrupted.")
    _report(pilot, ticks, broker)
    engine.storage.close()
    return 0


def _linked_notifier(settings, account: str):
    """The pending push's notifier: Approve/Skip links, signed as the web
    signs them, for the paper account only (a dry-run, replay or live push
    carries just "Open").

    The links are served by ``tradebot-web`` on the same database; with
    ``TRADEBOT_WEB_TOKEN`` set in both processes they share one secret, and a
    paper link signed here verifies against the web's paper pilot (same label).
    """
    from ..autopilot.links import env_secret, link_signer

    if account != "paper":
        return settings.build_notifier()
    return settings.build_notifier(link_signer(env_secret(), account, settings.poll_seconds))


def _build(settings, args):
    """(engine, data, broker-or-None, replay) as `run` would choose, or None."""
    if args.dry_run:
        built = _build_dry_engine(settings, args)
        if built is None:
            return None
        engine, data, broker, _, replay = built
        return engine, data, broker, replay
    if not _resolve_universe(settings):
        return None
    from .run import _build_paper_engine

    engine = _build_paper_engine(settings)
    return engine, engine.data, None, False


def _report(pilot, ticks, broker) -> None:
    state = pilot.state()
    print(f"[AUTOPILOT] ticks={ticks} mode={state.mode} pending={state.pending} "
          f"last_pass={state.last_pass_at} last_error={state.last_error}")
    if broker is not None:
        _print_dryrun_summary(broker)
