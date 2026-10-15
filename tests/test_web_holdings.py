"""The Today page's holdings card: broker positions, else the order log."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from tradebot.config import AlpacaCredentials  # noqa: E402
from tradebot.data.cache import BarCache  # noqa: E402
from tradebot.models import Order, Side  # noqa: E402
from tradebot.storage import Storage  # noqa: E402
from tradebot.web.services import advisor_service  # noqa: E402

from .test_web_today import (  # noqa: E402,F401
    _FakeBroker,
    _client,
    _config,
    _seed_cache,
    _seed_log,
    _store_dummy,
    offline,
)


def _last_close(tmp_path, symbol: str) -> float:
    return float(BarCache(tmp_path / "cache").load(symbol, "1day")["close"].iloc[-1])


def test_holdings_from_the_order_log_use_the_last_cached_close(tmp_path, offline):
    _seed_log(tmp_path)                          # paper: SPY +6, QQQ flat; equity 9,500
    _seed_cache(tmp_path)
    data = _client(tmp_path, _config(tmp_path)).get("/api/holdings").json()
    price = _last_close(tmp_path, "SPY")
    assert data["source"] == "log" and data["equity"] == 9_500.0
    assert data["skipped"] == [] and data["note"] is None
    (row,) = data["rows"]                        # QQQ netted flat: not a holding
    assert row["symbol"] == "SPY" and row["qty"] == 6.0
    assert row["price"] == pytest.approx(price)
    assert row["value"] == pytest.approx(6 * price)
    assert row["weight"] == pytest.approx(6 * price / 9_500.0)
    assert row["as_of"] == "2023-05-01"


def test_a_held_symbol_without_cached_bars_is_skipped_and_named(tmp_path, offline):
    _seed_log(tmp_path)
    with Storage(tmp_path / "t.db") as st:
        st.record_order(Order(symbol="XLK", qty=2, side=Side.BUY), None, "paper")
    _seed_cache(tmp_path, symbols=("SPY",))
    client = _client(tmp_path, _config(tmp_path))
    data = client.get("/api/holdings").json()
    assert [r["symbol"] for r in data["rows"]] == ["SPY"]
    assert data["skipped"] == ["XLK"]
    body = client.get("/partials/holdings").text
    assert "data-holdings-skipped" in body and "XLK" in body and "<html" not in body


def test_holdings_with_credentials_come_from_the_paper_broker(tmp_path, monkeypatch):
    monkeypatch.setattr(advisor_service, "_credentials",
                        lambda: AlpacaCredentials(api_key="k", api_secret="s"))
    monkeypatch.setattr(advisor_service, "_paper_broker", lambda creds: _FakeBroker())
    _seed_log(tmp_path)                          # ignored: the broker is the truth
    client = _client(tmp_path, _config(tmp_path))
    data = client.get("/api/holdings").json()    # empty cache: cost basis stands in
    assert data["source"] == "alpaca" and data["equity"] == 25_000.0
    assert data["rows"] == [{"symbol": "SPY", "qty": 4.0, "price": 100.0, "value": 400.0,
                             "weight": pytest.approx(400 / 25_000), "as_of": "cost basis"}]
    _seed_cache(tmp_path, symbols=("SPY",))
    row = client.get("/api/holdings").json()["rows"][0]
    assert row["price"] == pytest.approx(_last_close(tmp_path, "SPY"))


def test_a_broker_failure_falls_back_to_the_log_and_says_so(tmp_path, monkeypatch):
    def broken(creds):
        raise ConnectionError("down")

    monkeypatch.setattr(advisor_service, "_credentials",
                        lambda: AlpacaCredentials(api_key="k", api_secret="s"))
    monkeypatch.setattr(advisor_service, "_paper_broker", broken)
    _seed_log(tmp_path)
    _seed_cache(tmp_path)
    data = _client(tmp_path, _config(tmp_path)).get("/api/holdings").json()
    assert data["source"] == "log" and [r["symbol"] for r in data["rows"]] == ["SPY"]
    assert "order log" in data["note"]


def test_the_today_page_shows_holdings_under_the_account_strip(tmp_path, offline):
    _seed_log(tmp_path)
    _seed_cache(tmp_path)
    _store_dummy(tmp_path)
    client = _client(tmp_path, _config(tmp_path))
    body = client.get("/today").text
    assert body.index("data-account-source") < body.index("data-holdings") < body.index(
        'data-line="SPY"')
    assert 'data-holding="SPY"' in body and "from the order log" in body
    assert 'data-holding="SPY"' in client.get("/partials/proposal").text


def test_an_empty_book_says_nothing_is_held(tmp_path, offline):
    body = _client(tmp_path, _config(tmp_path)).get("/today").text
    assert "data-empty" in body and "data-no-holdings" in body
