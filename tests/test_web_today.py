"""Today page: the latest proposal on a phone, and the refresh that computes it."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from tradebot.storage import Storage  # noqa: E402
from tradebot.web.app import create_app  # noqa: E402

from .test_advisor import dummy_proposal  # noqa: E402


def _config(tmp_path, symbols=("SPY", "QQQ"), extra: str = "") -> str:
    path = tmp_path / "config.yaml"
    path.write_text(
        "mode: paper\n"
        f"symbols: [{', '.join(symbols)}]\n"
        "strategy:\n  name: sma_crossover\n  params: {fast: 5, slow: 20}\n" + extra
    )
    return str(path)


def _client(tmp_path, settings_path: str | None = None) -> TestClient:
    return TestClient(create_app(trading_db=str(tmp_path / "t.db"),
                                 arena_db=str(tmp_path / "a.db"),
                                 cache_dir=str(tmp_path / "cache"),
                                 settings_path=settings_path))


def _store_dummy(tmp_path) -> None:
    with Storage(tmp_path / "t.db") as st:
        st.record_proposal(dummy_proposal(), "paper")


def test_today_page_renders_empty_state_with_refresh_hint(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)                  # no config.yaml in the CWD
    body = _client(tmp_path).get("/today").text
    assert "data-empty" in body
    assert "Tap Refresh" in body
    assert "SPY, QQQ" in body                    # the default symbols
    assert "cp config.example.yaml config.yaml" in body


def test_today_page_with_a_config_drops_the_config_hint(tmp_path):
    body = _client(tmp_path, _config(tmp_path, ("XLK",))).get("/today").text
    assert "Tap Refresh" in body and "XLK" in body
    assert "config.example.yaml" not in body


def test_today_page_shows_the_stored_proposal(tmp_path):
    _store_dummy(tmp_path)
    body = _client(tmp_path, _config(tmp_path)).get("/today").text
    assert 'data-line="SPY"' in body and 'data-line="QQQ"' in body
    assert "sma_crossover signals long" in body
    assert "$1,000.00" in body                   # notional of the buy
    assert "$10,000.00" in body and "$4,000.00" in body
    assert "paper (from log)" in body
    assert 'data-created-at="2025-10-15T14:30:00+00:00"' in body
    assert "data-empty" not in body


def test_proposal_api_returns_lines_provenance_and_age(tmp_path):
    _store_dummy(tmp_path)
    data = _client(tmp_path, _config(tmp_path)).get("/api/proposal").json()
    assert data["configured"] is True and data["config_hint"] is None
    p = data["proposal"]
    assert p["account_label"] == "paper (from log)"
    assert p["provenance"]["source"] == "cache"
    assert p["age_seconds"] > 0
    assert [(ln["symbol"], ln["action"], ln["order_qty"]) for ln in p["lines"]] == [
        ("SPY", "buy", 10.0), ("QQQ", "hold", 0.0)]


def test_proposal_api_is_empty_before_the_first_refresh(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    data = _client(tmp_path).get("/api/proposal").json()
    assert data["proposal"] is None
    assert data["symbols"] == ["SPY", "QQQ"]
    assert data["config_hint"]


def test_proposal_partial_matches_the_page_list(tmp_path):
    _store_dummy(tmp_path)
    body = _client(tmp_path, _config(tmp_path)).get("/partials/proposal").text
    assert 'data-line="SPY"' in body and "<html" not in body
