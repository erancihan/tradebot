"""Which symbols the advisor and the autopilot scan: the watchlist, else config.

One resolver for both, so the Today page's suggestions and the autopilot's
trades can never be computed over different lists. The watchlist is edited
here too: validation lives in one place, and the store only ever holds
upper-case symbols that passed it.
"""

from __future__ import annotations

from dataclasses import replace

from ...models import SYMBOL_RE  # noqa: F401 - re-exported for the web
from ...storage import Storage
from ...storage.watchlist import active_symbols, resolve_active


class InvalidSymbols(ValueError):
    """One or more symbols failed ``SYMBOL_RE``."""


#: ``{symbols, source}``: the core's one resolver (``storage/watchlist.py``),
#: shared with the CLI so every process trades the same list.
resolve = resolve_active


def with_active_symbols(settings, store):
    """A copy of ``settings`` whose ``symbols`` is the active list."""
    return replace(settings, symbols=active_symbols(settings, store))


def clean(symbols: list[str]) -> list[str]:
    """Upper-cased, de-duplicated symbols; raises ``InvalidSymbols`` on any bad one."""
    out = list(dict.fromkeys(str(s).strip().upper() for s in symbols))
    bad = [s for s in out if not SYMBOL_RE.match(s)]
    if bad:
        raise InvalidSymbols(f"not a symbol: {', '.join(bad) or '(empty)'}")
    return out


def add_keeping_list(store, settings, symbols: list[str]) -> None:
    """Put cleaned ``symbols`` on the watchlist without dropping the active list.

    An empty watchlist means the config symbols are active; adding names as-is
    would make them the whole list, and the next pass would sell every held
    config name as off-list. So the empty case seeds the config symbols first
    (they are valid: ``config_load`` refuses a bad one).
    """
    if not store.watchlist():
        store.add_to_watchlist(list(settings.symbols))
    store.add_to_watchlist(symbols)


def change(settings, trading_db: str, *, add: list[str] | None = None,
           remove: list[str] | None = None) -> dict:
    """Apply one edit and return the resolved list after it."""
    with Storage(trading_db) as store:
        if add is not None:
            add_keeping_list(store, settings, clean(add))
        if remove is not None:
            store.remove_from_watchlist(clean(remove))
        return resolve(settings, store)
