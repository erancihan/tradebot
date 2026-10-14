"""Autopilot page: the runner's mode and state on a phone, and the commands."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from tradebot.storage import Storage  # noqa: E402
from tradebot.web.app import create_app  # noqa: E402


@pytest.fixture(autouse=True)
def _no_credentials(monkeypatch):
    """Offline: the autopilot runs as a dry-run over cached bars."""
    for key in ("ALPACA_API_KEY", "ALPACA_API_SECRET"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr("tradebot.config.AlpacaCredentials.from_env", lambda: None)


def _client(tmp_path) -> TestClient:
    return TestClient(create_app(trading_db=str(tmp_path / "t.db"),
                                 arena_db=str(tmp_path / "a.db"),
                                 cache_dir=str(tmp_path / "cache")))


def test_autopilot_page_shows_mode_and_pending(tmp_path):
    body = _client(tmp_path).get("/autopilot").text
    for key in ("off", "approve", "auto"):
        assert f'data-mode="{key}"' in body
    assert "Approve first" in body and "Automatic" in body
    assert 'data-mode="off" aria-pressed="true"' in body     # never touched = off
    assert "dry_run" in body and "stopped" in body
    assert "data-no-pending" in body


def test_autopilot_api_returns_the_state(tmp_path):
    data = _client(tmp_path).get("/api/autopilot").json()
    assert data["state"]["mode"] == "off"
    assert data["state"]["running"] is False
    assert data["state"]["account"] == "dry_run"
    assert [m["key"] for m in data["modes"]] == ["off", "approve", "auto"]
    assert data["pending"] == []


def test_mode_switch_through_the_api(tmp_path):
    client = _client(tmp_path)
    data = client.post("/api/autopilot", json={"mode": "approve"}).json()
    assert data["state"]["mode"] == "approve"
    assert data["state"]["started_at"] is not None
    with Storage(tmp_path / "t.db") as st:                  # it is durable
        assert st.autopilot_values("dry_run")["mode"] == "approve"
    assert 'data-mode="approve" aria-pressed="true"' in client.get("/partials/autopilot").text


@pytest.mark.parametrize("body", [{"mode": "live"}, {}, {"mode": "auto", "approve": [1]}])
def test_bad_commands_are_refused(tmp_path, body):
    """No mode reaches a live account, and a command means exactly one thing."""
    resp = _client(tmp_path).post("/api/autopilot", json=body)
    assert resp.status_code in (400, 422)
