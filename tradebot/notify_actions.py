"""What an ntfy push says, and the buttons a pending batch's push carries.

``ntfy_text`` flattens an event to lines a lock screen can show. With a
``public_url`` and a link signer, ``actions_header`` turns a ``pending_trades``
event into ntfy's ``Actions`` header (https://docs.ntfy.sh/publish/#action-buttons):
"Approve all" and "Skip" POST the batch's signed links from the phone, "Open"
opens the Autopilot page. The signer comes from ``tradebot.autopilot.links``;
this module never imports the web layer.
"""

from __future__ import annotations

import logging
import re
from typing import Callable
from urllib.parse import urlsplit

log = logging.getLogger("tradebot.notify")

#: ``signer(batch_id, verb) -> "exp=...&sig=..."``
LinkSigner = Callable[[int, str], str]

#: Sent by ntfy with each http action, so the server's same-origin guard holds.
_HTTP_OPTS = "method=POST, headers.X-Requested-With=tradebot, clear=true"

#: Nothing ntfy's Actions header could split on (quote, comma, semicolon,
#: whitespace) and nothing a header cannot carry.
_URL_CHARS = re.compile(r"[A-Za-z0-9._~:/%-]+", re.ASCII)


def safe_public_url(url: object) -> str | None:
    """``url`` without its trailing slash when it is a plain http(s) address
    (a host, no userinfo, query or fragment) safe inside an Actions header;
    else None. The Settings save and every push use this one check."""
    if not isinstance(url, str):
        return None
    url = url.rstrip("/")
    if _URL_CHARS.fullmatch(url) is None:
        return None
    try:
        parts = urlsplit(url)
        parts.port                      # raises on a malformed port
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname \
            or parts.query or parts.fragment or parts.username:
        return None
    return url


def ntfy_text(event: dict) -> str:
    """One line a person can read on a lock screen."""
    if "message" in event:
        return str(event["message"])
    rest = " ".join(f"{k}={v}" for k, v in event.items()
                    if k not in ("type", "lines") and v is not None)
    lines = [f"{ln.get('action', '')} {ln.get('qty', '')} {ln.get('symbol', '')}".strip()
             for ln in event.get("lines") or []]
    return "\n".join([rest, *lines]).strip() or str(event.get("type", "event"))


def batch_link(public_url: str, batch_id: int, verb: str, signer: LinkSigner) -> str:
    return (f"{public_url.rstrip('/')}/api/autopilot/batches/{int(batch_id)}/{verb}"
            f"?{signer(int(batch_id), verb)}")


def actions_header(event: dict, public_url: str | None,
                   signer: LinkSigner | None) -> str | None:
    """The ``Actions`` header for a pending batch, or None (no buttons).

    URLs are double-quoted: a signed link carries ``=`` and ntfy's simple
    format splits on it otherwise. A public URL that fails ``safe_public_url``
    (a hand-edited config.yaml) gives a plain push and one warning.

    A live account's push gets no Approve button: the link rides through the
    ntfy topic, so whoever reads the topic could use it. Skip is harmless.
    """
    batch_id = event.get("batch_id")
    if (event.get("type") != "pending_trades" or batch_id is None
            or not public_url or signer is None):
        return None
    public_url = safe_public_url(public_url)
    if public_url is None:
        log.warning("notify.public_url is not a plain http(s) address; "
                    "the push goes without buttons")
        return None
    actions = []
    if event.get("mode") != "live":
        approve = batch_link(public_url, batch_id, "approve", signer)
        actions.append(f'http, Approve all, "{approve}", {_HTTP_OPTS}')
    reject = batch_link(public_url, batch_id, "reject", signer)
    actions.append(f'http, Skip, "{reject}", {_HTTP_OPTS}')
    actions.append(f'view, Open, "{public_url}/autopilot"')
    return "; ".join(actions)
