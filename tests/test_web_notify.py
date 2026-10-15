"""The Autopilot page's test-alert button: one message through every channel."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from tradebot.web.app import create_app  # noqa: E402
from tradebot.web.guard import POST_HEADERS  # noqa: E402

from .test_notify import PlainTextServer  # noqa: E402
from .web_client import local_client  # noqa: E402


def _client(tmp_path, notify_block: str = ""):
    config = tmp_path / "config.yaml"
    config.write_text("symbols: [SPY]\n" + notify_block)
    return local_client(create_app(trading_db=str(tmp_path / "t.db"),
                                   arena_db=str(tmp_path / "a.db"),
                                   cache_dir=str(tmp_path / "cache"),
                                   settings_path=str(config)))


def test_the_test_alert_reaches_ntfy(tmp_path):
    server = PlainTextServer()
    try:
        client = _client(tmp_path, f"notify:\n  ntfy_topic: phone\n  ntfy_server: {server.url}\n")
        r = client.post("/api/notify/test", headers=POST_HEADERS)
    finally:
        server.close()
    assert r.status_code == 200
    assert r.json() == {"sent": True, "channels": ["log", "ntfy"], "failed": []}
    (got,) = server.received
    assert got["path"] == "/phone" and got["body"] == "tradebot test alert"
    assert got["headers"]["Title"] == "tradebot: test"


def test_an_unreachable_channel_is_reported_not_raised(tmp_path):
    client = _client(tmp_path, "notify:\n  ntfy_topic: phone\n"
                               "  ntfy_server: http://127.0.0.1:1\n")
    data = client.post("/api/notify/test", headers=POST_HEADERS).json()
    assert data == {"sent": False, "channels": ["log", "ntfy"], "failed": ["ntfy"]}


def test_log_only_is_sent_and_the_post_is_guarded(tmp_path):
    client = _client(tmp_path)
    assert client.post("/api/notify/test").status_code == 403
    assert client.post("/api/notify/test", headers=POST_HEADERS).json() == {
        "sent": True, "channels": ["log"], "failed": []}


def test_the_autopilot_page_has_the_test_alert_button(tmp_path):
    body = _client(tmp_path).get("/autopilot").text
    assert "data-test-alert" in body and "Send test alert" in body
    assert 'testAlert()' in body
