"""Outbound notifications: tell someone when the bot acts or stops.

A trading loop that runs unattended is only useful if it can reach you. This is
the smallest thing that does that: a ``Notifier`` protocol with one method, a
logging default, and a webhook adapter built on stdlib ``urllib`` so nothing new
enters the dependency set.

Two rules the engine relies on:

- **Delivery never blocks a trade.** Every failure — a dead endpoint, a DNS
  error, a timeout — is logged and swallowed. A notifier is an observer; if it
  could raise, an unreachable webhook would halt trading, which is exactly
  backwards.
- **Events are plain dicts** with a ``type`` key, JSON-serialisable as-is. That
  keeps the contract legible in a webhook payload and makes a recording
  notifier a two-line test double.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Protocol
from urllib.parse import urlsplit

log = logging.getLogger("tradebot.notify")


def masked_url(url: str) -> str:
    """``scheme://host[:port]/…last4`` for logs: a webhook path and an ntfy
    topic are bearer secrets, and ``user:pass@`` never belongs in a log."""
    try:
        parts = urlsplit(url)
        scheme, port = parts.scheme, parts.port
        host = f"{parts.hostname or ''}{f':{port}' if port else ''}"
    except ValueError:
        scheme = host = ""
    return f"{scheme}://{host}/\u2026{url[-4:]}"


def _failure(url: str, exc: Exception) -> str:
    """The error text with the URL masked (a ValueError can quote it whole)."""
    return str(exc).replace(url, masked_url(url))


class Notifier(Protocol):
    def send(self, event: dict) -> None: ...


class LogNotifier:
    """Default: write the event to the log. Always available, never fails."""

    def __init__(self, level: int = logging.INFO) -> None:
        self.level = level

    def send(self, event: dict) -> None:
        log.log(self.level, "event %s", event)


class NullNotifier:
    """Drops everything (for tests and for callers that want silence)."""

    def send(self, event: dict) -> None:
        pass


class WebhookNotifier:
    """POSTs the event as JSON to ``url``.

    Failures are logged and swallowed — see the module docstring. The timeout is
    short on purpose: the engine calls this inline on the trade path, so a
    hanging endpoint must cost a few seconds at most, not a whole poll interval.
    """

    def __init__(self, url: str, timeout: float = 5.0) -> None:
        self.url = url
        self.timeout = timeout

    def send(self, event: dict) -> None:
        self.deliver(event)

    def deliver(self, event: dict) -> bool:
        """Send one event; True when the endpoint accepted it."""
        payload = json.dumps(event).encode("utf-8")
        req = urllib.request.Request(
            self.url, data=payload,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if resp.status >= 400:
                    log.warning("Webhook %s returned HTTP %s",
                                masked_url(self.url), resp.status)
                return resp.status < 400
        except (urllib.error.URLError, OSError, ValueError) as exc:
            # One line, no traceback: an unattended bot with a dead endpoint
            # emits one of these per order, and a stack trace per event would
            # bury the trading log that actually matters.
            log.warning("Webhook delivery to %s failed: %s", masked_url(self.url),
                        _failure(self.url, exc))
            return False


class MultiNotifier:
    """Fans one event out to several notifiers; one failure never stops the rest."""

    def __init__(self, notifiers) -> None:
        self.notifiers = list(notifiers)

    def send(self, event: dict) -> None:
        for n in self.notifiers:
            try:
                n.send(event)
            except Exception:
                log.warning("Notifier %r failed", n, exc_info=True)


class NtfyNotifier:
    """Phone push through ntfy: POSTs plain text to ``{server}/{topic}``.

    ntfy shows the body as the notification text and the ``Title`` header as
    its heading, so the event is flattened to one readable line instead of
    JSON. Failures are logged and swallowed, as for the webhook.
    """

    def __init__(self, topic: str, server: str = "https://ntfy.sh",
                 timeout: float = 5.0) -> None:
        self.url = f"{server.rstrip('/')}/{topic.strip('/')}"
        self.timeout = timeout

    def send(self, event: dict) -> None:
        self.deliver(event)

    def deliver(self, event: dict) -> bool:
        """Send one event; True when the server accepted it."""
        title = f"tradebot: {event.get('type', 'event')}"
        req = urllib.request.Request(
            self.url, data=ntfy_text(event).encode("utf-8"), method="POST",
            # A header must be latin-1; a symbol or reason never needs more.
            headers={"Title": title.encode("latin-1", "replace").decode("latin-1"),
                     "Content-Type": "text/plain; charset=utf-8"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.status < 400
        except (urllib.error.URLError, OSError, ValueError) as exc:
            log.warning("ntfy delivery to %s failed: %s", masked_url(self.url),
                        _failure(self.url, exc))
            return False


def ntfy_text(event: dict) -> str:
    """One line a person can read on a lock screen."""
    if "message" in event:
        return str(event["message"])
    rest = " ".join(f"{k}={v}" for k, v in event.items()
                    if k not in ("type", "lines") and v is not None)
    lines = [f"{ln.get('action', '')} {ln.get('qty', '')} {ln.get('symbol', '')}".strip()
             for ln in event.get("lines") or []]
    return "\n".join([rest, *lines]).strip() or str(event.get("type", "event"))


def notifier_channels(webhook_url: str | None = None, ntfy_topic: str | None = None,
                      ntfy_server: str | None = None) -> list[tuple[str, Notifier]]:
    """(name, notifier) for every configured channel, the log always first."""
    channels: list[tuple[str, Notifier]] = [("log", LogNotifier())]
    if webhook_url:
        channels.append(("webhook", WebhookNotifier(webhook_url)))
    if ntfy_topic:
        channels.append(("ntfy", NtfyNotifier(ntfy_topic, ntfy_server or "https://ntfy.sh")))
    return channels


def build_notifier(webhook_url: str | None = None, ntfy_topic: str | None = None,
                   ntfy_server: str | None = None) -> Notifier:
    """The configured notifier: log-only by default, plus webhook and ntfy when set.

    The log is always included, never replaced: the log line is the local
    audit trail and stays useful when a remote endpoint is down.
    """
    channels = notifier_channels(webhook_url, ntfy_topic, ntfy_server)
    if len(channels) == 1:
        return channels[0][1]
    return MultiNotifier(n for _, n in channels)
