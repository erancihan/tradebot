"""Settings page: edit config.yaml from a phone, never a secret, never live."""

from __future__ import annotations

from unittest.mock import patch

import pytest
import yaml

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from tradebot.web.app import create_app  # noqa: E402
from tradebot.web.guard import POST_HEADERS  # noqa: E402
from tradebot.web.services import autopilot_service  # noqa: E402

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
    body = _client(tmp_path, _config(tmp_path)).get("/autopilot").text
    assert body.count('href="/settings"') == 2


# --- saving -------------------------------------------------------------------

def _doc(client) -> dict:
    return client.get("/api/settings").json()["settings"]


def _post(client, doc):
    return client.post("/api/settings", headers=POST_HEADERS, json=doc)


def test_save_writes_the_file_and_reloads_the_server_settings(tmp_path):
    path = _config(tmp_path, "db_path: custom.db\n")
    app = create_app(trading_db=str(tmp_path / "t.db"), arena_db=str(tmp_path / "a.db"),
                     cache_dir=str(tmp_path / "cache"), settings_path=path)
    client = local_client(app)
    doc = _doc(client)
    doc["symbols"] = ["vti", "BND"]
    doc["strategy"] = {"name": "buy_and_hold", "params": {}}
    resp = _post(client, doc)
    assert resp.status_code == 200, resp.text
    assert resp.headers["cache-control"] == "no-store"
    assert resp.json()["settings"]["symbols"] == ["VTI", "BND"]
    assert app.state.settings.symbols == ["VTI", "BND"]
    assert app.state.settings.strategy_name == "buy_and_hold"
    raw = yaml.safe_load(open(path))
    assert raw["symbols"] == ["VTI", "BND"]
    assert raw["db_path"] == "custom.db" and raw["mode"] == "paper"   # untouched keys stay


def test_save_creates_the_config_when_there_is_none(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = _client(tmp_path)
    doc = _doc(client)
    doc["symbols"] = ["XLV"]
    assert _post(client, doc).status_code == 200
    raw = yaml.safe_load((tmp_path / "config.yaml").read_text())
    assert raw["mode"] == "paper" and raw["symbols"] == ["XLV"]
    assert client.get("/api/settings").json()["config_exists"] is True


def test_save_rejects_a_bad_strategy_name_with_a_readable_message(tmp_path):
    path = _config(tmp_path)
    before = open(path).read()
    client = _client(tmp_path, path)
    doc = _doc(client)
    doc["strategy"] = {"name": "sma_crosover", "params": {}}
    resp = _post(client, doc)
    assert resp.status_code == 400
    assert resp.json()["detail"].startswith("strategy: Unknown strategy 'sma_crosover'")
    assert open(path).read() == before


@pytest.mark.parametrize("change, words", [
    ({"symbols": []}, "at least one symbol"),
    ({"symbols": ["S P Y"]}, "not a symbol"),
    ({"risk": {"max_position_pct": 5}}, "max_position_pct must be in [0, 1]"),
    ({"market": "nyse"}, "market must be one of"),
    ({"poll_seconds": 1}, "at least 10"),
    ({"api_key": "x"}, "not an editable setting: api_key"),
])
def test_save_rejects_documents_that_would_not_run(tmp_path, change, words):
    client = _client(tmp_path, _config(tmp_path))
    resp = _post(client, {**_doc(client), **change})
    assert resp.status_code == 400 and words in resp.json()["detail"]


def test_mode_cannot_be_set_to_live_from_the_web(tmp_path):
    path = _config(tmp_path)
    client = _client(tmp_path, path)
    resp = _post(client, {**_doc(client), "mode": "live"})
    assert resp.status_code == 422
    assert "mode: paper" in open(path).read()


def test_save_needs_the_same_origin_header(tmp_path):
    client = _client(tmp_path, _config(tmp_path))
    assert client.post("/api/settings", json=_doc(client)).status_code == 403


def test_save_reloads_the_server_settings_and_resets_the_autopilot(tmp_path):
    app = create_app(trading_db=str(tmp_path / "t.db"), arena_db=str(tmp_path / "a.db"),
                     cache_dir=str(tmp_path / "cache"), settings_path=_config(tmp_path))
    client = local_client(app)

    class FakePilot:
        running = True
        stopped = False

        def stop(self):
            self.stopped = True

    pilot = FakePilot()
    app.state.autopilot = pilot
    doc = _doc(client)
    doc["poll_seconds"] = 600
    data = _post(client, doc).json()
    assert pilot.stopped and autopilot_service.current(app) is None
    assert "autopilot loop was stopped" in data["notice"]
    assert app.state.settings.poll_seconds == 600
    with patch.object(autopilot_service.autopilot_build, "build", lambda s, **k: s):
        assert autopilot_service.get(app).poll_seconds == 600    # rebuilt from the new file


# --- alert destinations are masked --------------------------------------------

_ALERTS = ("notify:\n  webhook_url: https://hooks.example.com/services/T0/B0/abcdSECRETwxyz\n"
           "  ntfy_topic: tradebot-very-private-topic\n")


def test_alert_destinations_are_masked_in_the_view(tmp_path):
    client = _client(tmp_path, _config(tmp_path, _ALERTS))
    resp = client.get("/api/settings")
    assert resp.headers["cache-control"] == "no-store"
    data = resp.json()
    assert data["settings"]["notify"]["webhook_url"] == "https://hooks.example.com/\u2026wxyz"
    assert data["settings"]["notify"]["ntfy_topic"] == "tr\u2026ic"
    assert data["webhook_configured"] is True and data["ntfy_configured"] is True
    page = client.get("/settings")
    assert page.headers["cache-control"] == "no-store"
    assert "abcdSECRET" not in page.text and "very-private" not in page.text


def test_a_masked_or_missing_alert_keeps_the_stored_secret_on_save(tmp_path):
    path = _config(tmp_path, _ALERTS)
    client = _client(tmp_path, path)
    doc = _doc(client)                       # carries the masked webhook back
    del doc["notify"]["ntfy_topic"]          # not sent at all: keep
    assert _post(client, doc).status_code == 200
    raw = yaml.safe_load(open(path))["notify"]
    assert raw["webhook_url"].endswith("abcdSECRETwxyz")
    assert raw["ntfy_topic"] == "tradebot-very-private-topic"

    doc["notify"]["ntfy_topic"] = "a-new-topic"     # a plain value replaces it
    assert _post(client, doc).status_code == 200
    assert yaml.safe_load(open(path))["notify"]["ntfy_topic"] == "a-new-topic"


def test_an_emptied_alert_destination_is_removed_on_save(tmp_path):
    """Clearing a field is the only way to delete a destination from the page."""
    path = _config(tmp_path, _ALERTS)
    client = _client(tmp_path, path)
    doc = _doc(client)
    doc["notify"]["webhook_url"] = ""
    doc["notify"]["ntfy_topic"] = ""
    assert _post(client, doc).status_code == 200
    raw = yaml.safe_load(open(path)).get("notify") or {}
    assert not raw.get("webhook_url") and not raw.get("ntfy_topic")
    data = client.get("/api/settings").json()
    assert data["webhook_configured"] is False and data["ntfy_configured"] is False


# --- strategy and portfolio pickers ---------------------------------------------

def test_stack_lists_selectors_and_allocators_with_typed_params(tmp_path):
    data = _client(tmp_path).get("/api/stack").json()
    momentum = next(s for s in data["selectors"] if s["name"] == "momentum")
    assert {"name": "top_k", "type": "int", "default": 5} in momentum["params"]
    assert {"name": "reverse", "type": "bool", "default": False} in momentum["params"]
    assert [a["name"] for a in data["allocators"]] == ["equal", "inverse_vol"]


def test_settings_page_has_the_three_pickers(tmp_path):
    body = _client(tmp_path, _config(tmp_path)).get("/settings").text
    for kind in ("strategy", "selector", "allocation"):
        assert f'data-picker="{kind}"' in body
    assert "edit in the config file" in body


def test_save_a_picked_portfolio_keeps_the_overlays(tmp_path):
    path = _config(tmp_path, "portfolio:\n  allocation: equal\n  overlays:\n"
                             "    - name: vol_target\n      params: {target_vol: 0.2}\n")
    client = _client(tmp_path, path)
    doc = _doc(client)
    doc["strategy"] = {"name": "buy_and_hold", "params": {}}
    doc["portfolio"]["selector"] = {"name": "momentum", "params": {"lookback": 60, "skip": 5,
                                                                   "top_k": 1, "reverse": False}}
    doc["portfolio"]["allocation"] = "inverse_vol"
    doc["portfolio"]["params"] = {"window": 21, "gross_target": 1.0}
    assert _post(client, doc).status_code == 200
    raw = yaml.safe_load(open(path))["portfolio"]
    assert raw["selector"]["params"]["top_k"] == 1 and raw["allocation"] == "inverse_vol"
    assert raw["overlays"] == [{"name": "vol_target", "params": {"target_vol": 0.2}}]


def test_save_rejects_a_param_the_selector_does_not_take(tmp_path):
    client = _client(tmp_path, _config(tmp_path))
    doc = _doc(client)
    doc["portfolio"]["selector"] = {"name": "momentum", "params": {"topk": 2}}
    resp = _post(client, doc)
    assert resp.status_code == 400
    assert resp.json()["detail"].startswith("portfolio.selector:")


def test_the_webhook_mask_never_echoes_userinfo(tmp_path):
    alerts = "notify:\n  webhook_url: https://bob:hunter2@hooks.example.com:8443/x/abcd\n"
    data = _client(tmp_path, _config(tmp_path, alerts)).get("/api/settings").json()
    assert data["settings"]["notify"]["webhook_url"] == "https://hooks.example.com:8443/…abcd"
    assert "hunter2" not in str(data)


def test_a_kept_secret_must_still_point_where_it_did(tmp_path):
    path = _config(tmp_path, _ALERTS)
    client = _client(tmp_path, path)
    before = open(path).read()

    doc = _doc(client)
    doc["notify"]["ntfy_server"] = "https://ntfy.example.org"     # topic left masked
    resp = _post(client, doc)
    assert resp.status_code == 400 and "enter the topic again" in resp.json()["detail"]

    doc = _doc(client)
    doc["notify"]["webhook_url"] = "https://evil.example.net/…wxyz"
    resp = _post(client, doc)
    assert resp.status_code == 400 and "full webhook URL again" in resp.json()["detail"]
    assert open(path).read() == before


# --- setup card -----------------------------------------------------------------

def _seed_bars(tmp_path, symbols):
    from tradebot.data.cache import BarCache
    from tradebot.data.synthetic import synthetic_ohlcv

    cache = BarCache(tmp_path / "cache")
    for sym in symbols:
        cache.store(sym, "1day", synthetic_ohlcv(periods=30, seed=1))


def test_setup_status_reports_missing_config_credentials_and_bars(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    data = _client(tmp_path).get("/api/setup").json()
    assert data["ready"] is False
    assert data["config"]["ok"] is False and "Settings" in data["config"]["hint"]
    assert data["credentials"]["ok"] is False and ".env" in data["credentials"]["hint"]
    assert data["bars"]["ok"] is False and data["bars"]["missing"] == ["SPY", "QQQ"]
    hint = data["bars"]["hint"]
    assert "tradebot data pull --symbols SPY QQQ --timeframe 1day --start " in hint
    assert "--end " in hint


def test_setup_bars_hint_says_refresh_when_the_server_has_keys(tmp_path, monkeypatch):
    monkeypatch.setattr("tradebot.config.AlpacaCredentials.from_env", lambda: object())
    _seed_bars(tmp_path, ["XLK"])
    data = _client(tmp_path, _config(tmp_path)).get("/api/setup").json()
    assert data["config"]["ok"] and data["credentials"]["ok"]
    assert data["bars"]["missing"] == ["XLE"]
    assert data["bars"]["hint"].startswith("Tap Refresh")


def test_today_shows_the_setup_card_until_everything_is_ready(tmp_path, monkeypatch):
    path = _config(tmp_path)
    body = _client(tmp_path, path).get("/today").text
    assert "data-setup-card" in body
    assert 'data-setup-item="config" data-ok="true"' in body
    assert 'data-setup-item="credentials" data-ok="false"' in body

    monkeypatch.setattr("tradebot.config.AlpacaCredentials.from_env", lambda: object())
    _seed_bars(tmp_path, ["XLK", "XLE"])
    assert "data-setup-card" not in _client(tmp_path, path).get("/today").text


# --- autopilot, alerts, market, risk ------------------------------------------------

def test_settings_page_has_a_field_for_every_s5_setting(tmp_path):
    body = _client(tmp_path, _config(tmp_path)).get("/settings").text
    for name in ("poll_seconds", "brief_minutes_before_open", "ntfy_topic", "ntfy_server",
                 "public_url",
                 "webhook_url", "market", "timeframe", "initial_cash", "max_position_pct",
                 "max_gross_exposure", "max_daily_loss_pct", "rebalance_band_pct",
                 "stop_loss_pct", "take_profit_pct", "allow_fractional"):
        assert f'name="{name}"' in body, name


def test_save_autopilot_alerts_market_and_risk(tmp_path):
    path = _config(tmp_path)
    client = _client(tmp_path, path)
    doc = _doc(client)
    doc.update(poll_seconds=900, market="bist", timeframe="1day", initial_cash=2500)
    doc["autopilot"] = {"brief_minutes_before_open": 30}
    doc["notify"] = {"ntfy_topic": "my-topic-123", "ntfy_server": None, "webhook_url": None}
    doc["risk"].update(max_position_pct=0.25, stop_loss_pct=0.05, allow_fractional=True)
    assert _post(client, doc).status_code == 200
    raw = yaml.safe_load(open(path))
    assert raw["poll_seconds"] == 900 and raw["market"] == "bist"
    assert raw["autopilot"] == {"brief_minutes_before_open": 30}
    assert raw["notify"] == {"ntfy_topic": "my-topic-123"}
    assert raw["risk"]["max_position_pct"] == 0.25 and raw["risk"]["stop_loss_pct"] == 0.05
    assert raw["risk"]["allow_fractional"] is True

    doc = _doc(client)
    doc["autopilot"] = {"brief_minutes_before_open": None}      # the brief switched off
    doc["risk"]["stop_loss_pct"] = None
    assert _post(client, doc).status_code == 200
    raw = yaml.safe_load(open(path))
    assert "autopilot" not in raw and "stop_loss_pct" not in raw["risk"]
    assert raw["notify"]["ntfy_topic"] == "my-topic-123"         # masked in, kept


# --- the public URL (the push's Approve/Skip buttons) ------------------------------

def test_public_url_is_saved_shown_unmasked_and_hinted(tmp_path):
    path = _config(tmp_path, "notify:\n  ntfy_topic: my-topic-123\n")
    client = _client(tmp_path, path)
    doc = _doc(client)
    assert doc["notify"]["public_url"] is None
    doc["notify"]["public_url"] = "http://192.168.1.20:8000/"
    resp = _post(client, doc)
    assert resp.status_code == 200, resp.text
    assert resp.json()["settings"]["notify"]["public_url"] == "http://192.168.1.20:8000"
    raw = yaml.safe_load(open(path))
    assert raw["notify"] == {"ntfy_topic": "my-topic-123",          # the topic kept
                             "public_url": "http://192.168.1.20:8000"}
    assert _doc(client)["notify"]["public_url"] == "http://192.168.1.20:8000"
    page = client.get("/settings").text
    assert "Lets the phone push carry Approve and Skip buttons." in page

    doc = _doc(client)
    doc["notify"]["public_url"] = None                             # cleared
    assert _post(client, doc).status_code == 200
    assert "public_url" not in yaml.safe_load(open(path))["notify"]


@pytest.mark.parametrize("url", ["bot.example.net", "ftp://bot.example.net", "http://",
                                 "https://bot.example.net/?a=1", "https://u:p@bot.example.net",
                                 'https://bot.example.net/"x', "https://bot,example.net",
                                 "https://böt.example.net", "http://host:99999", 42])
def test_save_rejects_a_public_url_that_is_not_an_http_address(tmp_path, url):
    path = _config(tmp_path)
    client = _client(tmp_path, path)
    before = open(path).read()
    doc = _doc(client)
    doc["notify"]["public_url"] = url
    resp = _post(client, doc)
    assert resp.status_code == 400 and "notify.public_url" in resp.json()["detail"]
    assert open(path).read() == before


def test_a_public_url_with_a_path_is_accepted(tmp_path):
    client = _client(tmp_path, _config(tmp_path))
    doc = _doc(client)
    doc["notify"]["public_url"] = "https://example.net/tradebot"
    assert _post(client, doc).status_code == 200
