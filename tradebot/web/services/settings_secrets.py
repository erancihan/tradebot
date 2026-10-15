"""Alert destinations are bearer secrets: whoever knows them can post to them.

A webhook URL usually carries its token in the path, and an ntfy topic on the
public server is readable and writable by anyone who guesses it. The Settings
page therefore only ever sees a masked form, and a save that sends the mask
back (or nothing) keeps the stored value instead of overwriting it.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from .settings_validate import InvalidSettings

ELLIPSIS = "…"
#: notify keys treated as secrets; ``ntfy_server`` is a public host, not one.
MASKED_KEYS = ("webhook_url", "ntfy_topic")


def mask_url(url: str) -> str:
    """``scheme://host/…last4``: enough to recognise, not enough to use."""
    return f"{urlsplit(url).scheme}://{_host(url)}/{ELLIPSIS}{url[-4:]}"


def _host(url: str) -> str:
    """Host plus port, never ``netloc``: that would echo ``user:pass@``."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return ""
    return f"{parts.hostname or ''}{f':{port}' if port else ''}"


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


def _kept(value: Any) -> bool:
    """Blank, or the mask the page was given: "keep what is stored"."""
    return not value or ELLIPSIS in str(value)


def restore(posted: dict[str, Any] | None, stored: dict[str, Any]) -> dict[str, Any]:
    """The notify block to write: blank or masked values keep what is stored.

    A kept secret must still point where it did. A masked webhook is accepted
    only if its host is the stored host, and a kept topic only while the ntfy
    server is unchanged: otherwise the old secret would be sent somewhere new.
    """
    out = dict(posted or {})
    url, old_url = out.get("webhook_url"), stored.get("webhook_url")
    if _kept(url):
        if url and (not old_url or _host(str(url)) != _host(str(old_url))):
            raise InvalidSettings("notify.webhook_url: the host changed, so enter the "
                                  "full webhook URL again")
        out["webhook_url"] = old_url
    if _kept(out.get("ntfy_topic")):
        if (out.get("ntfy_server") or None) != (stored.get("ntfy_server") or None) \
                and stored.get("ntfy_topic"):
            raise InvalidSettings("notify.ntfy_topic: the ntfy server changed, so enter "
                                  "the topic again")
        out["ntfy_topic"] = stored.get("ntfy_topic")
    return out
