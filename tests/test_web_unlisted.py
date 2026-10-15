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
