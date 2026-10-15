"""Discover on the Today page: the job, the card, and Add to the watchlist."""

from __future__ import annotations

import re

import pandas as pd
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from tradebot.config import AlpacaCredentials  # noqa: E402
from tradebot.data.cache import BarCache  # noqa: E402
from tradebot.data.synthetic import synthetic_ohlcv  # noqa: E402
from tradebot.models import Order, Side  # noqa: E402
from tradebot.storage import Storage  # noqa: E402
from tradebot.universe.discover import discover  # noqa: E402
from tradebot.web.guard import POST_HEADERS  # noqa: E402
from tradebot.web.services import advisor_service  # noqa: E402
from tradebot.web.services.jobs import discover as discover_job  # noqa: E402

from .test_web_today import (  # noqa: E402,F401
    _FakeBroker,
    _client,
    _config,
    _seed_cache,
    _wait,
    offline,
)

POOL = ("AAA", "BBB", "CCC", "DDD", "SPY", "QQQ", "SYN_A")


def _run(client):
    r = client.post("/api/discover/run", headers=POST_HEADERS)
    assert r.status_code == 200
    return _wait(client, r.json()["job_id"])


def _rows(body: str) -> list[str]:
    return re.findall(r'data-discover-row="([A-Z._-]+)"', body)


def _seed_pool(tmp_path):
    _seed_cache(tmp_path, symbols=POOL, periods=300)
    with Storage(tmp_path / "t.db") as st:            # BBB is held in the paper log
        st.record_order(Order(symbol="BBB", qty=3, side=Side.BUY), None, "paper")


def test_the_job_ranks_the_cache_pool_and_the_today_page_shows_it(tmp_path, offline):
    _seed_pool(tmp_path)
    client = _client(tmp_path, _config(tmp_path))
    assert "data-discover-empty" in client.get("/today").text
    job = _run(client)
    assert job["state"] == "done", job["error"]
    prov = job["provenance"]
    assert prov["source"] == "cache" and prov["timeframe"] == "1day"
    assert prov["bars"] == 3 * 300 and prov["as_of"] and prov["start"] and prov["end"]
    assert prov["excluded"] == ["BBB", "QQQ", "SPY"]  # config symbols and the holding

    # The same ranking the core gives on the same frames, minus the excluded names.
    cache = BarCache(tmp_path / "cache")
    expected = discover(lambda syms: {s: cache.load(s, "1day") for s in syms},
                        ["AAA", "CCC", "DDD"])
    body = client.get("/today").text
    assert _rows(body) == [r.symbol for r in expected.rows]  # SYN_A is not a ticker
    assert "a day traded." in body and 'data-discover-source="cache"' in body
    assert body.index("data-discover") < body.index("Watchlist")


def test_add_puts_the_row_on_the_watchlist_and_it_survives_a_restart(tmp_path, offline):
    _seed_pool(tmp_path)
    client = _client(tmp_path, _config(tmp_path))
    assert _run(client)["state"] == "done"
    top = _rows(client.get("/partials/discover").text)[0]
    r = client.post("/api/discover/add", json={"symbol": top}, headers=POST_HEADERS)
    assert r.status_code == 200 and top in r.json()["symbols"]

    fresh = _client(tmp_path, _config(tmp_path))       # a restart: a new app
    body = fresh.get("/partials/discover").text
    row = body[body.index(f'data-discover-row="{top}"'):]
    row = row[:row.index("</li>")]
    assert "data-on-watchlist" in row and "data-add-symbol" not in row
    assert body.count("data-add-symbol") == len(_rows(body)) - 1
    view = fresh.get("/api/discover").json()
    assert view["run"]["source"] == "cache"
    assert [r["on_watchlist"] for r in view["run"]["rows"]][0] is True


def test_without_cache_or_credentials_the_job_says_how_to_fill_it(tmp_path, offline):
    job = _run(_client(tmp_path, _config(tmp_path)))
    assert job["state"] == "error"
    assert "tradebot data pull" in job["error"]


def test_the_run_endpoint_needs_the_guard_header(tmp_path):
    r = _client(tmp_path, _config(tmp_path)).post("/api/discover/run")
    assert r.status_code == 403


def _window_fetcher(calls):
    def fetch(symbol, timeframe, start, end):
        calls.append(symbol)
        days = (end - start).days
        df = synthetic_ohlcv(periods=days, start=str(start.date()), freq="1D",
                             seed=len(calls))
        return df[df.index <= end]
    return fetch


class _FakeUniverse:
    def resolve_details(self):
        return [{"symbol": s, "price": 100.0, "adv": 5e8}
                for s in ("AAA", "BBB", "SPY", "VTI")]


def test_with_credentials_the_pool_is_alpaca_and_bars_land_in_the_cache(tmp_path,
                                                                       monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(advisor_service, "_credentials",
                        lambda: AlpacaCredentials(api_key="k", api_secret="s"))
    monkeypatch.setattr(advisor_service, "build_default_fetcher",
                        lambda: _window_fetcher(calls))
    monkeypatch.setattr(advisor_service, "_paper_broker", lambda creds: _FakeBroker())
    monkeypatch.setattr(discover_job, "_universe", _FakeUniverse)
    client = _client(tmp_path, _config(tmp_path))
    assert "most-active" in client.get("/today").text      # the empty card's hint
    job = _run(client)
    assert job["state"] == "done", job["error"]
    assert job["provenance"]["source"] == "alpaca"
    assert sorted(calls) == ["AAA", "BBB", "VTI"]         # SPY is held and configured
    assert BarCache(tmp_path / "cache").load("VTI", "1day") is not None
    body = client.get("/partials/discover").text
    assert sorted(_rows(body)) == ["AAA", "BBB", "VTI"]
    assert 'data-discover-source="alpaca"' in body
    # as_of is the cut (today): no bar after it is read; end is the newest bar used.
    assert pd.Timestamp(job["provenance"]["end"]).date().isoformat() \
        <= job["provenance"]["as_of"]


def _add(client, symbol):
    return client.post("/api/discover/add", json={"symbol": symbol}, headers=POST_HEADERS)


def test_add_to_an_empty_watchlist_keeps_the_config_symbols(tmp_path):
    client = _client(tmp_path, _config(tmp_path))            # symbols: SPY, QQQ
    r = _add(client, "aapl")
    assert r.status_code == 200
    assert r.json() == {"symbols": ["SPY", "QQQ", "AAPL"], "source": "watchlist"}
    assert client.get("/api/watchlist").json()["symbols"] == ["SPY", "QQQ", "AAPL"]


def test_add_to_a_non_empty_watchlist_just_appends(tmp_path):
    client = _client(tmp_path, _config(tmp_path))
    client.post("/api/watchlist", json={"add": ["VTI"]}, headers=POST_HEADERS)
    assert _add(client, "AAPL").json()["symbols"] == ["VTI", "AAPL"]
    assert _add(client, "AAPL").json()["symbols"] == ["VTI", "AAPL"]   # no duplicate


@pytest.mark.parametrize("bad", ["1X", "", "SPY;--"])
def test_add_refuses_a_bad_symbol_and_stores_nothing(tmp_path, bad):
    client = _client(tmp_path, _config(tmp_path))
    r = _add(client, bad)
    assert r.status_code == 400 and "not a symbol" in r.json()["detail"]
    assert client.get("/api/watchlist").json()["source"] == "config"
    assert client.post("/api/discover/add", json={"symbol": "AAPL"}).status_code == 403


def test_add_stops_a_running_autopilot(tmp_path, offline):
    from tradebot.web.services import autopilot_service

    _seed_cache(tmp_path, symbols=("SPY", "QQQ"))
    client = _client(tmp_path, _config(tmp_path))
    on = client.post("/api/autopilot", headers=POST_HEADERS, json={"mode": "auto"})
    assert on.json()["state"]["running"] is True
    pilot = autopilot_service.current(client.app)
    r = _add(client, "AAPL")
    assert r.status_code == 200 and "tap a mode" in r.json()["notice"]
    assert autopilot_service.current(client.app) is None
    pilot._thread.join(5)
    assert not pilot.running


def _alpaca_client(tmp_path, monkeypatch, fetcher):
    monkeypatch.setattr(advisor_service, "_credentials",
                        lambda: AlpacaCredentials(api_key="k", api_secret="s"))
    monkeypatch.setattr(advisor_service, "build_default_fetcher", lambda: fetcher)
    monkeypatch.setattr(advisor_service, "_paper_broker", lambda creds: _FakeBroker())
    monkeypatch.setattr(discover_job, "_universe", _FakeUniverse)
    return _client(tmp_path, _config(tmp_path))


def test_a_search_where_every_fetch_fails_errors_and_keeps_the_last_run(tmp_path,
                                                                        monkeypatch):
    calls: list[str] = []
    good = _window_fetcher(calls)
    state = {"down": False}

    def fetch(symbol, timeframe, start, end):
        if state["down"]:
            raise ConnectionError("network unreachable")
        return good(symbol, timeframe, start, end)

    client = _alpaca_client(tmp_path, monkeypatch, fetch)
    assert _run(client)["state"] == "done"
    before = client.get("/api/discover").json()["run"]
    for sym in ("AAA", "BBB", "VTI"):             # nothing cached: every name refetches
        for p in (tmp_path / "cache" / "1day").glob(f"{sym}.*"):
            p.unlink()
    state["down"] = True
    job = _run(client)
    assert job["state"] == "error"
    assert "could be fetched" in job["error"] and "ConnectionError" in job["error"]
    after = client.get("/api/discover").json()["run"]
    assert after["id"] == before["id"] and after["rows"] == before["rows"]


def test_a_search_where_some_fetches_fail_says_how_many(tmp_path, monkeypatch):
    calls: list[str] = []
    good = _window_fetcher(calls)

    def fetch(symbol, timeframe, start, end):
        if symbol == "VTI":
            raise TimeoutError("slow")
        return good(symbol, timeframe, start, end)

    client = _alpaca_client(tmp_path, monkeypatch, fetch)
    job = _run(client)
    assert job["state"] == "done", job["error"]
    assert job["provenance"]["failed"] == 1
    assert job["provenance"]["failed_error"] == "TimeoutError"
    body = client.get("/partials/discover").text
    assert "1 name could not be fetched" in body and "data-discover-failed" in body
    assert sorted(_rows(body)) == ["AAA", "BBB"]
