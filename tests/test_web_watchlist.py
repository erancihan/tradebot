"""Watchlist: the symbols the owner scans, edited from the Today page."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from tradebot.config import Settings  # noqa: E402
from tradebot.storage import Storage  # noqa: E402
from tradebot.web.guard import POST_HEADERS  # noqa: E402
from tradebot.web.services import autopilot_build  # noqa: E402

from .test_web_today import _client, _config, _refresh, _seed_cache, offline  # noqa: E402,F401


def _post(client, body):
    return client.post("/api/watchlist", json=body, headers=POST_HEADERS)


def test_an_empty_watchlist_falls_back_to_the_config(tmp_path):
    client = _client(tmp_path, _config(tmp_path))
    assert client.get("/api/watchlist").json() == {"symbols": ["SPY", "QQQ"],
                                                   "source": "config"}
    body = client.get("/today").text
    assert "Your watchlist is empty" in body and "the config symbols" in body


def test_add_uppercases_dedupes_and_keeps_order(tmp_path):
    client = _client(tmp_path, _config(tmp_path))
    r = _post(client, {"add": [" vti ", "brk.b", "VTI", "bf-b"]})
    assert r.status_code == 200
    assert r.json() == {"symbols": ["VTI", "BRK.B", "BF-B"], "source": "watchlist"}
    _post(client, {"add": ["VTI"]})                       # re-adding is a no-op
    assert len(client.get("/api/watchlist").json()["symbols"]) == 3
    r = _post(client, {"remove": ["vti"]})
    assert "VTI" not in r.json()["symbols"] and r.json()["source"] == "watchlist"


@pytest.mark.parametrize("bad", ["1X", "", "TOOLONGSYMBOL", "SP Y", "SPY;--"])
def test_invalid_symbols_are_refused_and_nothing_is_stored(tmp_path, bad):
    client = _client(tmp_path, _config(tmp_path))
    r = _post(client, {"add": ["XLK", bad]})
    assert r.status_code == 400
    assert "not a symbol" in r.json()["detail"]
    assert client.get("/api/watchlist").json()["source"] == "config"


@pytest.mark.parametrize("body", [{}, {"add": ["A"], "remove": ["B"]}])
def test_exactly_one_of_add_or_remove(tmp_path, body):
    assert _post(_client(tmp_path, _config(tmp_path)), body).status_code == 400


def test_a_watchlist_edit_needs_the_same_origin_header(tmp_path):
    client = _client(tmp_path, _config(tmp_path))
    assert client.post("/api/watchlist", json={"add": ["XLK"]}).status_code == 403


def test_the_today_page_shows_chips_and_names_the_list(tmp_path):
    client = _client(tmp_path, _config(tmp_path))
    _post(client, {"add": ["XLK", "GLD"]})
    body = client.get("/today").text
    assert 'data-remove-symbol="XLK"' in body and 'data-remove-symbol="GLD"' in body
    assert "XLK, GLD" in body and "(your watchlist)" in body
    partial = client.get("/partials/watchlist").text
    assert 'data-remove-symbol="XLK"' in partial and "<html" not in partial


def test_watchlist_overrides_config_symbols_for_the_advisor_and_autopilot(tmp_path, offline):
    _seed_cache(tmp_path, symbols=("SPY", "QQQ", "XLK"))
    client = _client(tmp_path, _config(tmp_path))         # config: SPY, QQQ
    _post(client, {"add": ["xlk"]})

    job = _refresh(client)
    assert job["state"] == "done", job["error"]
    lines = client.get("/api/proposal").json()["proposal"]["lines"]
    assert [ln["symbol"] for ln in lines] == ["XLK"]

    settings = Settings(symbols=["SPY", "QQQ"], strategy_name="buy_and_hold")
    pilot = autopilot_build.build(settings, trading_db=str(tmp_path / "t.db"),
                                  cache_dir=str(tmp_path / "cache"))
    try:
        assert pilot.engine.settings.symbols == ["XLK"]
        assert list(pilot.engine.data.history("XLK", "1day").columns)  # replay over XLK
    finally:
        pilot.storage.close()
    assert settings.symbols == ["SPY", "QQQ"]            # the server's copy is untouched


def test_storage_watchlist_roundtrip(tmp_path):
    with Storage(tmp_path / "t.db") as st:
        assert st.watchlist() == []
        st.add_to_watchlist(["SPY", "QQQ"])
        st.add_to_watchlist(["SPY"])
        st.remove_from_watchlist(["QQQ", "NOPE"])
        assert st.watchlist() == ["SPY"]
