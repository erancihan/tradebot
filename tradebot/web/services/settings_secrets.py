"""Alert destinations are bearer secrets: whoever knows them can post to them.

A webhook URL usually carries its token in the path, and an ntfy topic on the
public server is readable and writable by anyone who guesses it. The Settings
page therefore only ever sees a masked form, and a save that sends the mask
back (or nothing) keeps the stored value instead of overwriting it.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

ELLIPSIS = "…"
#: notify keys treated as secrets; ``ntfy_server`` is a public host, not one.
MASKED_KEYS = ("webhook_url", "ntfy_topic")


def mask_url(url: str) -> str:
    """``scheme://host/…last4``: enough to recognise, not enough to use."""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}/{ELLIPSIS}{url[-4:]}"


def mask_topic(topic: str) -> str:
    return f"{topic[:2]}{ELLIPSIS}{topic[-2:]}" if len(topic) > 4 else ELLIPSIS


def _mask(key: str, value: str) -> str:
    return mask_url(value) if key == "webhook_url" else mask_topic(value)


def masked(notify: dict[str, Any]) -> dict[str, Any]:
    """The notify block as the page may see it."""
    out = dict(notify)
    for key in MASKED_KEYS:
        if out.get(key):
            out[key] = _mask(key, str(out[key]))
    return out


def configured(notify: dict[str, Any]) -> dict[str, bool]:
    return {"webhook_configured": bool(notify.get("webhook_url")),
            "ntfy_configured": bool(notify.get("ntfy_topic"))}


def restore(posted: dict[str, Any] | None, stored: dict[str, Any]) -> dict[str, Any]:
    """The notify block to write: blank or masked values keep what is stored."""
    out = dict(posted or {})
    for key in MASKED_KEYS:
        value = out.get(key)
        old = stored.get(key)
        if not value or (old and value == _mask(key, str(old))) or ELLIPSIS in str(value):
            out[key] = old
    return out
