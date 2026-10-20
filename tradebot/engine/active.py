"""The active list, re-read at the start of every pass.

A watchlist edit on the phone stops only the web's own loop; a ``tradebot run``
in another process keeps its engine. So the engine itself re-resolves the list
from its storage each pass (``storage.watchlist.resolve_active``), with the
symbols it was built with as the fallback: an added name is proposed on the
next pass, and a removed one is closed as an off-list holding.
"""

from __future__ import annotations

import logging
from dataclasses import replace

from ..storage.watchlist import resolve_active

log = logging.getLogger("tradebot.engine")


class _Fallback:
    """What ``resolve_active`` reads as "the config": the engine's own list."""

    def __init__(self, symbols: list[str]) -> None:
        self.symbols = symbols


def refresh(engine) -> None:
    """Point ``engine.settings`` at the active list; log once when it changes.

    Without a storage the list is the one the engine was built with. A failed
    read keeps the current list for this pass.
    """
    if engine.storage is None:
        return
    try:
        active = resolve_active(_Fallback(engine._config_symbols), engine.storage)
    except Exception:  # noqa: BLE001 - a watchlist read never kills the pass
        log.exception("Watchlist read failed; keeping %s this pass", engine.settings.symbols)
        return
    symbols = list(active["symbols"])
    if symbols == list(engine.settings.symbols):
        return
    # The watchlist replaces any universe screen, as the CLI's start does.
    universe = None if active["source"] == "watchlist" else engine._config_universe
    engine.settings = replace(engine.settings, symbols=symbols, universe_name=universe)
    log.info("Active list: symbols=%s(%d) %s", active["source"], len(symbols), symbols)
