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

log = logging.getLogger("tradebot.notify")


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
        payload = json.dumps(event).encode("utf-8")
        req = urllib.request.Request(
            self.url, data=payload,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if resp.status >= 400:
                    log.warning("Webhook %s returned HTTP %s", self.url, resp.status)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            # One line, no traceback: an unattended bot with a dead endpoint
            # emits one of these per order, and a stack trace per event would
            # bury the trading log that actually matters.
            log.warning("Webhook delivery to %s failed: %s", self.url, exc)


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


def build_notifier(webhook_url: str | None = None) -> Notifier:
    """The configured notifier: log-only by default, log+webhook when set.

    Both, not webhook-only: the log line is the local audit trail and stays
    useful when the remote endpoint is down.
    """
    if not webhook_url:
        return LogNotifier()
    return MultiNotifier([LogNotifier(), WebhookNotifier(webhook_url)])
