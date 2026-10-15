"""The list is the mandate on Today: a held name off the list gets a
sell-to-flat line, and removing a held name says so before it happens."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from tradebot.config import AlpacaCredentials  # noqa: E402
from tradebot.data.cache import BarCache  # noqa: E402
from tradebot.models import Order, Position, Side  # noqa: E402
from tradebot.storage import Storage  # noqa: E402
from tradebot.web.guard import POST_HEADERS  # noqa: E402
from tradebot.web.services import advisor_service  # noqa: E402

from .test_web_today import (  # noqa: E402
    _client, _config, _FakeBroker, _FakeFetcher, _refresh, _seed_cache, offline,  # noqa: F401
)


def _lines(client) -> dict[str, dict]:
    return {ln["symbol"]: ln for ln in client.get("/api/proposal").json()["proposal"]["lines"]}


def test_refresh_offline_sells_an_order_log_position_off_the_list(tmp_path, offline):
    _seed_cache(tmp_path, ("SPY", "QQQ", "IWM"))
    with Storage(tmp_path / "t.db") as st:
        st.record_order(Order(symbol="IWM", qty=5, side=Side.BUY), None, "paper")
        st.record_order(Order(symbol="DIA", qty=2, side=Side.BUY), None, "paper")  # uncached
    client = _client(tmp_path, _config(tmp_path))
    assert _refresh(client)["state"] == "done"
    lines = _lines(client)
    assert list(lines) == ["SPY", "QQQ", "DIA", "IWM"]
    iwm = lines["IWM"]
    close = float(BarCache(tmp_path / "cache").load("IWM", "1day")["close"].iloc[-1])
    assert (iwm["action"], iwm["order_qty"], iwm["desired_qty"]) == ("sell", -5.0, 0.0)
    assert iwm["price"] == pytest.approx(close)
    assert iwm["reason"] == "not on your list: sell to flat"
    assert lines["DIA"]["reason"] == "not on your list; no price to size it"
    assert lines["DIA"]["order_qty"] == 0
    body = client.get("/partials/proposal").text
    assert 'data-line="IWM"' in body and "not on your list: sell to flat" in body


class _HoldsIwm(_FakeBroker):
    def positions(self):
        return {**super().positions(), "IWM": Position("IWM", qty=-3.0, avg_price=200.0)}


def test_refresh_with_the_paper_broker_closes_its_off_list_short(tmp_path, monkeypatch):
    monkeypatch.setattr(advisor_service, "_credentials",
                        lambda: AlpacaCredentials(api_key="k", api_secret="s"))
    monkeypatch.setattr(advisor_service, "build_default_fetcher", _FakeFetcher)
    monkeypatch.setattr(advisor_service, "_paper_broker", lambda creds: _HoldsIwm())
    _seed_cache(tmp_path, ("IWM",))
    client = _client(tmp_path, _config(tmp_path))
    assert _refresh(client)["state"] == "done"
    iwm = _lines(client)["IWM"]
    assert (iwm["action"], iwm["order_qty"]) == ("buy", 3.0)
    assert iwm["reason"] == "not on your list: buy to flat"


def test_remove_confirmation_names_the_shares_only_when_held(tmp_path, offline):
    with Storage(tmp_path / "t.db") as st:
        st.record_order(Order(symbol="QQQ", qty=13, side=Side.BUY), None, "paper")
    client = _client(tmp_path, _config(tmp_path))
    client.post("/api/watchlist", json={"add": ["QQQ", "SPY"]}, headers=POST_HEADERS)
    held = ('data-remove-confirm="Remove QQQ? You hold 13 shares; '
            'the autopilot sells them at its next pass."')
    for url in ("/today", "/partials/watchlist"):
        body = client.get(url).text
        assert held in body, url
        assert 'data-remove-confirm="Remove SPY?"' in body, url


def _online(monkeypatch, broker):
    fetcher = _FakeFetcher()
    monkeypatch.setattr(advisor_service, "_credentials",
                        lambda: AlpacaCredentials(api_key="k", api_secret="s"))
    monkeypatch.setattr(advisor_service, "build_default_fetcher", lambda: fetcher)
    monkeypatch.setattr(advisor_service, "_paper_broker", lambda creds: broker)
    return fetcher


def test_refresh_fetches_an_uncached_off_list_name_as_the_engine_would(tmp_path, monkeypatch):
    fetcher = _online(monkeypatch, _HoldsIwm())       # IWM held, never cached
    client = _client(tmp_path, _config(tmp_path))
    assert _refresh(client)["state"] == "done"
    iwm = _lines(client)["IWM"]
    assert (iwm["action"], iwm["order_qty"]) == ("buy", 3.0) and iwm["price"] > 0
    assert "IWM" in [c[0] for c in fetcher.calls]


def test_refresh_offline_still_skips_an_uncached_off_list_name(tmp_path, offline):
    _seed_cache(tmp_path)
    with Storage(tmp_path / "t.db") as st:
        st.record_order(Order(symbol="IWM", qty=5, side=Side.BUY), None, "paper")
    client = _client(tmp_path, _config(tmp_path))
    assert _refresh(client)["state"] == "done"
    assert _lines(client)["IWM"]["reason"] == "not on your list; no price to size it"


def test_manage_unlisted_false_keeps_today_off_off_list_names(tmp_path, offline):
    _seed_cache(tmp_path, ("SPY", "QQQ", "IWM"))
    with Storage(tmp_path / "t.db") as st:
        st.record_order(Order(symbol="IWM", qty=5, side=Side.BUY), None, "paper")
    client = _client(tmp_path, _config(tmp_path, extra="manage_unlisted: false\n"))
    assert _refresh(client)["state"] == "done"
    assert list(_lines(client)) == ["SPY", "QQQ"]


class _HoldsCrypto(_FakeBroker):
    def positions(self):
        return {**super().positions(),
                "BTCUSD": Position("BTCUSD", 0.5, 60000.0, asset_class="crypto")}


def test_today_ignores_a_crypto_position_as_the_engine_pass_does(tmp_path, monkeypatch):
    """Today == a pass: the engine never reads a crypto position as an
    off-list equity, so Today shows no line for it either."""
    _online(monkeypatch, _HoldsCrypto())
    client = _client(tmp_path, _config(tmp_path))
    assert _refresh(client)["state"] == "done"
    assert "BTCUSD" not in _lines(client)


def _live_config(tmp_path) -> str:
    path = tmp_path / "config.yaml"
    path.write_text("mode: live\nsymbols: [SPY, QQQ]\n"
                    "strategy:\n  name: sma_crossover\n  params: {fast: 5, slow: 20}\n")
    return str(path)


def test_today_on_a_live_config_never_sells_an_off_list_name(tmp_path, offline):
    """One rule with the engine (``manages_unlisted_for``): live never sells
    what it did not buy, whatever ``manage_unlisted`` says (on by default)."""
    _seed_cache(tmp_path, ("SPY", "QQQ", "IWM"))
    with Storage(tmp_path / "t.db") as st:
        st.record_order(Order(symbol="IWM", qty=5, side=Side.BUY), None, "live")
    client = _client(tmp_path, _live_config(tmp_path))
    assert _refresh(client)["state"] == "done"
    assert list(_lines(client)) == ["SPY", "QQQ"]


_STAYS = ('data-remove-confirm="Remove QQQ? You hold 13 shares; they stay in the '
          'account (the autopilot does not sell names off the list)."')


@pytest.mark.parametrize("live", [False, True])
def test_remove_confirmation_never_promises_a_sale_the_autopilot_will_not_make(
        tmp_path, offline, live):
    """With ``manage_unlisted: false``, or on live (never sells what it did not
    buy), removing a held name leaves it in the account, and the question says so."""
    mode = "live" if live else "paper"
    with Storage(tmp_path / "t.db") as st:
        st.record_order(Order(symbol="QQQ", qty=13, side=Side.BUY), None, mode)
    path = (_live_config(tmp_path) if live
            else _config(tmp_path, extra="manage_unlisted: false\n"))
    client = _client(tmp_path, path)
    client.post("/api/watchlist", json={"add": ["QQQ", "SPY"]}, headers=POST_HEADERS)
    for url in ("/today", "/partials/watchlist"):
        body = client.get(url).text
        assert _STAYS in body, url
        assert "sells them at its next pass" not in body, url
