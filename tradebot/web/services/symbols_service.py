"""Which symbols the advisor and the autopilot scan: the watchlist, else config.

One resolver for both, so the Today page's suggestions and the autopilot's
trades can never be computed over different lists. The watchlist is edited
here too: validation lives in one place, and the store only ever holds
upper-case symbols that passed it.
"""

from __future__ import annotations

import re
from dataclasses import replace

from ...storage import Storage

#: Letters plus the dot and dash some tickers carry (BRK.B, BF-B).
SYMBOL_RE = re.compile(r"^[A-Z.\-]{1,10}$")


class InvalidSymbols(ValueError):
    """One or more symbols failed ``SYMBOL_RE``."""


def resolve(settings, store) -> dict:
    """``{symbols, source}``: the watchlist when it has any, else the config.

    ``store`` is anything with ``watchlist()``: the read-only web repository
    or a ``Storage``.
    """
    watched = store.watchlist()
    if watched:
        return {"symbols": watched, "source": "watchlist"}
    return {"symbols": list(settings.symbols), "source": "config"}


def active_symbols(settings, store) -> list[str]:
    return resolve(settings, store)["symbols"]


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


def change(settings, trading_db: str, *, add: list[str] | None = None,
           remove: list[str] | None = None) -> dict:
    """Apply one edit and return the resolved list after it."""
    with Storage(trading_db) as store:
        if add is not None:
            store.add_to_watchlist(clean(add))
        if remove is not None:
            store.remove_from_watchlist(clean(remove))
        return resolve(settings, store)
