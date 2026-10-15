"""Settings page: edit config.yaml from a phone, never a secret, never live."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from tradebot.web.app import create_app  # noqa: E402
from tradebot.web.guard import POST_HEADERS  # noqa: E402, F401

from .web_client import local_client  # noqa: E402


@pytest.fixture(autouse=True)
def _no_credentials(monkeypatch):
    for key in ("ALPACA_API_KEY", "ALPACA_API_SECRET"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr("tradebot.config.AlpacaCredentials.from_env", lambda: None)


def _config(tmp_path, body: str = "") -> str:
    path = tmp_path / "config.yaml"
    path.write_text("mode: paper\nsymbols: [XLK, XLE]\n"
                    "strategy:\n  name: sma_crossover\n  params: {fast: 5, slow: 20}\n" + body)
    return str(path)


def _client(tmp_path, settings_path: str | None = None) -> TestClient:
    return local_client(create_app(trading_db=str(tmp_path / "t.db"),
                                   arena_db=str(tmp_path / "a.db"),
                                   cache_dir=str(tmp_path / "cache"),
                                   settings_path=settings_path))


def test_settings_api_returns_the_editable_document(tmp_path):
    data = _client(tmp_path, _config(tmp_path)).get("/api/settings").json()
    s = data["settings"]
    assert s["symbols"] == ["XLK", "XLE"]
    assert s["strategy"] == {"name": "sma_crossover", "params": {"fast": 5, "slow": 20}}
    assert s["risk"]["max_position_pct"] == 0.10
    assert "mode" not in s and "db_path" not in s       # not editable from the web
    assert data["mode"] == "paper"
    assert data["credentials_present"] is False
    assert data["config_exists"] is True and data["config_path"].endswith("config.yaml")
    assert "us_equities" in data["choices"]["markets"]


def test_settings_api_without_a_config_points_at_the_default_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    data = _client(tmp_path).get("/api/settings").json()
    assert data["config_path"] == "config.yaml" and data["config_exists"] is False
    assert data["settings"]["symbols"] == ["SPY", "QQQ"]


def test_settings_page_renders_the_sections_and_never_a_key(tmp_path, monkeypatch):
    monkeypatch.setattr("tradebot.config.AlpacaCredentials.from_env",
                        lambda: object())
    monkeypatch.setenv("ALPACA_API_SECRET", "s3cr3t-value")
    body = _client(tmp_path, _config(tmp_path)).get("/settings").text
    for title in ("Symbols", "Strategy", "Portfolio", "Risk", "Autopilot", "Alerts", "Market"):
        assert f">{title}<" in body
    assert "present" in body and "s3cr3t-value" not in body
    assert "not editable here" in body


def test_settings_is_in_the_more_sheet_and_the_top_nav(tmp_path):
    body = _client(tmp_path, _config(tmp_path)).get("/today").text
    assert body.count('href="/settings"') == 2
