"""What an ntfy push says, and the buttons a pending batch's push carries.

``ntfy_text`` flattens an event to lines a lock screen can show. With a
``public_url`` and a link signer, ``actions_header`` turns a ``pending_trades``
event into ntfy's ``Actions`` header (https://docs.ntfy.sh/publish/#action-buttons):
"Approve all" and "Skip" POST the batch's signed links from the phone, "Open"
opens the Autopilot page. The signer comes from ``tradebot.autopilot.links``;
this module never imports the web layer.
"""

from __future__ import annotations

from typing import Callable

#: ``signer(batch_id, verb) -> "exp=...&sig=..."``
LinkSigner = Callable[[int, str], str]

#: Sent by ntfy with each http action, so the server's same-origin guard holds.
_HTTP_OPTS = "method=POST, headers.X-Requested-With=tradebot, clear=true"


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
    format splits on it otherwise. The text is latin-1 safe because a header
    must be; a public URL is plain ASCII by validation.
    """
    batch_id = event.get("batch_id")
    if (event.get("type") != "pending_trades" or batch_id is None
            or not public_url or signer is None):
        return None
    approve = batch_link(public_url, batch_id, "approve", signer)
    reject = batch_link(public_url, batch_id, "reject", signer)
    text = (f'http, Approve all, "{approve}", {_HTTP_OPTS}; '
            f'http, Skip, "{reject}", {_HTTP_OPTS}; '
            f'view, Open, "{public_url.rstrip("/")}/autopilot"')
    return text.encode("latin-1", "replace").decode("latin-1")
