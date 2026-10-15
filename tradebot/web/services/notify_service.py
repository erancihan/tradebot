"""The Autopilot page's "Send test alert": one message through every channel.

The trading path swallows delivery failures on purpose (a notifier never
breaks a trade). A test button that swallowed them too would say "sent" for a
mistyped topic, so this asks each remote channel whether it was accepted.
"""

from __future__ import annotations

from ...notify import notifier_channels

TEST_MESSAGE = "tradebot test alert"


def send_test(settings) -> dict:
    """Send the test message; ``sent`` is True when every channel accepted it."""
    channels = notifier_channels(settings.notify_webhook_url, settings.notify_ntfy_topic,
                                 settings.notify_ntfy_server)
    event = {"type": "test", "message": TEST_MESSAGE}
    failed = []
    for name, notifier in channels:
        deliver = getattr(notifier, "deliver", None)
        if deliver is None:
            notifier.send(event)          # the log: always works
        elif not deliver(event):
            failed.append(name)
    return {"sent": not failed, "channels": [name for name, _ in channels],
            "failed": failed}
