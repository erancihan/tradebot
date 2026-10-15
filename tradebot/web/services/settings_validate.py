"""Is a posted settings document one the trading core can run?

``Settings.from_dict`` alone accepts a misspelled strategy (the name is only
looked up when the engine builds it), so a save that merely parsed could write
a config the autopilot then fails on. Validation therefore builds every
component the document names, and turns whatever they raise into one readable
sentence for the page.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from ...config import Settings
from ...data.alpaca_data import _TIMEFRAME_ALIASES
from . import symbols_service


class InvalidSettings(ValueError):
    """The document would not load or would not build; the message says why."""


def _reason(exc: Exception) -> str:
    # str(KeyError("x")) is "'x'": the registries put the readable text in args.
    return str(exc.args[0]) if isinstance(exc, KeyError) and exc.args else str(exc)


def validate(doc: dict[str, Any]) -> Settings:
    """The ``Settings`` the document describes, or ``InvalidSettings``."""
    _check_shape(doc)
    try:
        settings = Settings.from_dict(doc)
    except (TypeError, ValueError, KeyError, AttributeError) as exc:
        raise InvalidSettings(_reason(exc)) from exc
    _check_numbers(settings)
    _check_public_url(settings.notify_public_url)
    for section, build in (
        ("strategy", lambda: _build_strategy(settings)),
        ("portfolio.selector", settings.build_selector),
        ("portfolio.allocation", settings.build_allocator),
        ("portfolio.overlays", settings.build_overlays),
    ):
        try:
            build()
        except (TypeError, ValueError, KeyError) as exc:
            raise InvalidSettings(f"{section}: {_reason(exc)}") from exc
    return settings


def _build_strategy(settings: Settings):
    from ...strategies import build_strategy

    return build_strategy(settings.strategy_name, settings.strategy_params)


def _check_shape(doc: dict[str, Any]) -> None:
    symbols = doc.get("symbols")
    if not isinstance(symbols, list) or not symbols:
        raise InvalidSettings("symbols: give at least one symbol")
    try:
        doc["symbols"] = symbols_service.clean(symbols)
    except symbols_service.InvalidSymbols as exc:
        raise InvalidSettings(f"symbols: {exc}") from exc
    if doc.get("timeframe", "1day") not in _TIMEFRAME_ALIASES:
        raise InvalidSettings(f"timeframe must be one of {', '.join(_TIMEFRAME_ALIASES)}")
    for block in ("strategy", "portfolio", "risk", "notify", "autopilot"):
        if doc.get(block) is not None and not isinstance(doc[block], dict):
            raise InvalidSettings(f"{block} must be an object")
    notify = doc.get("notify") or {}
    if isinstance(notify.get("public_url"), str):      # the file says what is used
        notify["public_url"] = notify["public_url"].strip().rstrip("/") or None


def _check_numbers(settings: Settings) -> None:
    if settings.poll_seconds < 10:
        raise InvalidSettings("poll_seconds must be at least 10")
    if settings.initial_cash <= 0:
        raise InvalidSettings("initial_cash must be more than 0")
    brief = settings.brief_minutes_before_open
    if brief is not None and (not isinstance(brief, int) or not 0 <= brief <= 720):
        raise InvalidSettings("autopilot.brief_minutes_before_open must be 0 to 720 minutes")


#: Characters ntfy's Actions header would split on, plus anything non-ASCII.
_UNSAFE_URL = re.compile(r"[\s\"',;]|[^\x21-\x7e]")


def _check_public_url(url: str | None) -> None:
    """An http(s) address with a host, safe to put in an ntfy Actions header."""
    if url is None:
        return
    reason = "notify.public_url must be an http(s) address, e.g. http://192.168.1.20:8000"
    if not isinstance(url, str) or _UNSAFE_URL.search(url):
        raise InvalidSettings(reason)
    try:
        parts = urlsplit(url)
        parts.port                      # raises on a malformed port
    except ValueError as exc:
        raise InvalidSettings(reason) from exc
    if parts.scheme not in ("http", "https") or not parts.hostname \
            or parts.query or parts.fragment or parts.username:
        raise InvalidSettings(reason)
