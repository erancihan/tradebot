"""Build the web process's one Autopilot from the server settings.

With Alpaca credentials the engine trades the **paper** account (the broker
is always the paper endpoint here, whatever the config says, so the web can
never reach a live account). Without them it is a dry-run over the cached
bars: a ``DryRunBroker`` on a ``ReplayData`` parked at the newest cached bar,
so every pass trades on the latest data the machine has and nothing touches
the network.
"""

from __future__ import annotations

from datetime import date

from ...autopilot import Autopilot
from ...config import AlpacaCredentials
from ...data.cache import BarCache
from ...storage import Storage
from . import symbols_service
from .jobs.frames import _pull_hint


def build(settings, *, trading_db: str, cache_dir: str,
          link_secret: bytes | None = None, links_persist: bool = False) -> Autopilot:
    """``link_secret`` signs the push's Approve/Skip links (``autopilot.links``),
    armed for the paper account only: the dry-run push carries just "Open".
    ``links_persist``: the key survives restarts (it comes from the access
    token), so a restart does not push an announced batch again."""
    from ...autopilot.links import link_signer
    from ...engine import Engine
    from ...risk import RiskManager
    from ...strategies import build_strategy

    # The engine re-reads the watchlist every pass (``engine.active``), with
    # the config symbols as its fallback; the dry-run's frames need it now.
    with Storage(trading_db) as store:
        active = symbols_service.with_active_symbols(settings, store)
    creds = AlpacaCredentials.from_env()
    broker, data, label = (_paper(creds) if creds is not None
                           else _dry_run(active, cache_dir))
    storage = Storage(trading_db, check_same_thread=False)
    if label == "dry_run":               # a fresh virtual account: History starts here
        storage.record_account_start(label)
    engine = Engine(settings, broker, data,
                    build_strategy(settings.strategy_name, settings.strategy_params),
                    RiskManager(settings.risk), storage, mode_label=label,
                    # The broker is paper or simulated by construction above,
                    # so the live latch has nothing to guard here.
                    enforce_live_ack=False,
                    allocator=settings.build_allocator(),
                    selector=settings.build_selector(),
                    overlays=settings.build_overlays(),
                    notifier=settings.build_notifier(
                        link_signer(link_secret, label, settings.poll_seconds)
                        if link_secret and label == "paper" else None))
    return Autopilot(engine, storage, poll_seconds=settings.poll_seconds,
                     links_persist=links_persist)


def _paper(creds):
    from ...data import get_alpaca_data
    from .advisor_service import _paper_broker

    data = get_alpaca_data(creds.api_key, creds.api_secret, feed=creds.feed)
    return _paper_broker(creds), data, "paper"


def _dry_run(settings, cache_dir: str):
    from ...broker.dryrun import DryRunBroker
    from ...data.replay import ReplayData

    frames = cached_frames(settings.symbols, settings.timeframe, cache_dir)
    data = ReplayData(frames, warmup=len(next(iter(frames.values()))))
    broker = DryRunBroker(data, timeframe=settings.timeframe,
                          initial_cash=settings.initial_cash,
                          slippage_bps=settings.slippage_bps,
                          commission=settings.commission)
    return broker, data, "dry_run"


def cached_frames(symbols, timeframe: str, cache_dir: str) -> dict:
    """Every symbol's cached bars on the dates they all share.

    ReplayData reveals the first N rows of each frame, so frames of unequal
    length would put different dates side by side; the shared index keeps
    every row a single date.
    """
    cache, frames, missing = BarCache(cache_dir), {}, []
    for sym in symbols:
        try:
            frames[sym] = cache.get(sym, timeframe, fetcher=None)
        except RuntimeError:
            missing.append(sym)
    if missing:
        today = date.today()
        hint = _pull_hint(" ".join(missing), timeframe,
                          today.replace(year=today.year - 2).isoformat(), today.isoformat())
        raise RuntimeError(f"No Alpaca credentials and no cached bars for "
                           f"{', '.join(missing)}. Pull once with: {hint}")
    shared = None
    for df in frames.values():
        shared = df.index if shared is None else shared.intersection(df.index)
    if shared is None or len(shared) < 2:
        raise RuntimeError("The cached bars share fewer than 2 dates; pull a common window.")
    return {s: df.loc[shared] for s, df in frames.items()}
