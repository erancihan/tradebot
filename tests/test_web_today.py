"""Today page: the latest proposal on a phone, and the refresh that computes it."""

from __future__ import annotations

import time

import pandas as pd
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from .web_client import local_client  # noqa: E402

from tradebot.config import AlpacaCredentials  # noqa: E402
from tradebot.data.cache import BarCache  # noqa: E402
from tradebot.data.synthetic import synthetic_ohlcv  # noqa: E402
from tradebot.models import Order, Side  # noqa: E402
from tradebot.storage import Storage  # noqa: E402
from tradebot.web.app import create_app  # noqa: E402
from tradebot.web.guard import POST_HEADERS  # noqa: E402
from tradebot.web.services import advisor_service  # noqa: E402

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
    return local_client(create_app(trading_db=str(tmp_path / "t.db"),
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
    assert 'href="/settings"' in body and "Open Settings" in body
    assert "cp config.example.yaml" not in body


def test_today_page_with_a_config_drops_the_config_hint(tmp_path):
    body = _client(tmp_path, _config(tmp_path, ("XLK",))).get("/today").text
    assert "Tap Refresh" in body and "XLK" in body
    assert "Open Settings" not in body


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


# --- refresh: server-side, cache first, network only with credentials ----------

LOOKBACK = 25 + advisor_service.LOOKBACK_HEADROOM     # sma_crossover(5, 20) warmup + headroom


def _seed_cache(tmp_path, symbols=("SPY", "QQQ"), periods=120):
    cache = BarCache(tmp_path / "cache")
    for i, sym in enumerate(symbols):
        df = synthetic_ohlcv(periods=periods, seed=10 + i)
        cache.store(sym, "1day", df)
        cache.record_coverage(sym, "1day", df.index.min(), df.index.max())


def _wait(client, job_id, timeout=15.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["state"] in ("done", "error"):
            return job
        time.sleep(0.05)
    raise AssertionError("job did not finish in time")


def _refresh(client):
    r = client.post("/api/proposal/refresh", headers=POST_HEADERS)
    assert r.status_code == 200
    return _wait(client, r.json()["job_id"])


@pytest.fixture
def offline(monkeypatch):
    """No credentials, and any attempt to build a network fetcher fails loudly."""
    def no_fetcher():
        raise AssertionError("a fetcher was built without credentials")

    monkeypatch.setattr(advisor_service, "_credentials", lambda: None)
    monkeypatch.setattr(advisor_service, "build_default_fetcher", no_fetcher)


def test_refresh_job_uses_cached_bars_without_credentials(tmp_path, offline):
    _seed_cache(tmp_path)
    client = _client(tmp_path, _config(tmp_path))
    job = _refresh(client)
    assert job["state"] == "done", job["error"]
    assert job["kind"] == "proposal" and job["summary"]["lines"] == 2

    p = client.get("/api/proposal").json()["proposal"]
    assert [ln["symbol"] for ln in p["lines"]] == ["SPY", "QQQ"]
    for line in p["lines"]:
        assert line["action"] in ("buy", "sell", "hold")
        assert line["reason"].startswith("sma_crossover signals")
    prov = p["provenance"]
    assert prov["source"] == "cache"
    assert prov["bars"] == {"SPY": LOOKBACK, "QQQ": LOOKBACK}
    assert prov["end"].startswith("2023-05-01")              # the cached window
    assert prov["computed_at"] and prov["timeframe"] == "1day"
    assert p["account_label"] == "paper (starting cash)"
    assert p["equity"] == 10_000.0
    assert "data-line=\"SPY\"" in client.get("/partials/proposal").text


def test_refresh_job_fails_with_the_pull_hint_for_an_uncached_symbol(tmp_path, offline):
    _seed_cache(tmp_path, symbols=("SPY",))
    client = _client(tmp_path, _config(tmp_path, ("SPY", "NOPE")))
    job = _refresh(client)
    assert job["state"] == "error"
    assert "tradebot data pull --symbols NOPE --timeframe 1day --start" in job["error"]
    assert "no Alpaca credentials" in job["error"]
    assert client.get("/api/proposal").json()["proposal"] is None   # nothing stored


class _FakeFetcher:
    def __init__(self):
        self.calls: list[tuple] = []

    def __call__(self, symbol, timeframe, start, end):
        self.calls.append((symbol, timeframe, start, end))
        idx = pd.bdate_range(end=pd.Timestamp(end).normalize(), periods=90, tz="UTC")
        df = synthetic_ohlcv(periods=len(idx), seed=len(self.calls))
        df.index = idx
        return df


class _FakeBroker:
    def account(self):
        from tradebot.broker.base import AccountSnapshot

        return AccountSnapshot(equity=25_000.0, cash=20_000.0, buying_power=20_000.0,
                               is_paper=True)

    def positions(self):
        from tradebot.models import Position

        return {"SPY": Position("SPY", qty=4.0, avg_price=100.0)}


def test_refresh_job_attaches_a_fetcher_only_with_credentials(tmp_path, monkeypatch):
    fetcher = _FakeFetcher()
    monkeypatch.setattr(advisor_service, "_credentials",
                        lambda: AlpacaCredentials(api_key="k", api_secret="s"))
    monkeypatch.setattr(advisor_service, "build_default_fetcher", lambda: fetcher)
    monkeypatch.setattr(advisor_service, "_paper_broker", lambda creds: _FakeBroker())

    client = _client(tmp_path, _config(tmp_path))          # empty cache
    job = _refresh(client)
    assert job["state"] == "done", job["error"]
    assert [c[0] for c in fetcher.calls] == ["SPY", "QQQ"]
    p = client.get("/api/proposal").json()["proposal"]
    assert p["provenance"]["source"] == "alpaca"
    assert p["account_label"] == "paper (Alpaca)"
    assert (p["equity"], p["cash"]) == (25_000.0, 20_000.0)
    assert {ln["symbol"]: ln["current_qty"] for ln in p["lines"]}["SPY"] == 4.0
    # Every fetch landed in the cache, so the next refresh can replay offline.
    assert BarCache(tmp_path / "cache").load("QQQ", "1day") is not None


# --- account state from the SQLite log -----------------------------------------

def _seed_log(tmp_path):
    with Storage(tmp_path / "t.db") as st:
        st.record_equity(9_000.0, 8_000.0, "paper")
        st.record_equity(9_500.0, 8_100.0, "paper")
        st.record_equity(1.0, 1.0, "dry_run")                # another account
        for sym, qty, side, mode in (("SPY", 10, Side.BUY, "paper"),
                                     ("SPY", 4, Side.SELL, "paper"),
                                     ("QQQ", 3, Side.BUY, "paper"),
                                     ("QQQ", 3, Side.SELL, "paper"),
                                     ("SPY", 99, Side.BUY, "dry_run")):
            st.record_order(Order(symbol=sym, qty=qty, side=side), None, mode)


def test_positions_derived_from_the_order_log(tmp_path):
    from tradebot.web.repository import TradingRepository

    _seed_log(tmp_path)
    repo = TradingRepository(str(tmp_path / "t.db"))
    assert repo.positions_from_orders("paper") == {"SPY": 6.0}     # QQQ netted flat
    assert repo.positions_from_orders("dry_run") == {"SPY": 99.0}
    assert repo.latest_equity_for("paper")["equity"] == 9_500.0
    assert TradingRepository(str(tmp_path / "missing.db")).positions_from_orders("paper") == {}


def test_refresh_offline_reads_the_account_from_the_log(tmp_path, offline):
    _seed_log(tmp_path)
    _seed_cache(tmp_path)
    client = _client(tmp_path, _config(tmp_path))
    assert _refresh(client)["state"] == "done"
    p = client.get("/api/proposal").json()["proposal"]
    assert (p["equity"], p["cash"]) == (9_500.0, 8_100.0)
    assert p["account_label"] == "paper (from log)"
    assert {ln["symbol"]: ln["current_qty"] for ln in p["lines"]} == {"SPY": 6.0, "QQQ": 0.0}
    body = client.get("/today").text
    assert "paper (from log)" in body and "$9,500.00" in body and "$8,100.00" in body


def test_settings_come_from_an_explicit_path_then_cwd_then_defaults(tmp_path, monkeypatch):
    from tradebot.web.app import load_settings

    monkeypatch.chdir(tmp_path)
    settings, source = load_settings(None)
    assert source is None and settings.symbols == ["SPY", "QQQ"]
    assert settings.mode == "paper"
    _config(tmp_path, ("XLE",))                              # ./config.yaml appears
    settings, source = load_settings(None)
    assert source == "config.yaml" and settings.symbols == ["XLE"]
    other = tmp_path / "other.yaml"
    other.write_text("symbols: [GLD]\n")
    assert load_settings(str(other))[0].symbols == ["GLD"]


def test_load_settings_reads_tradebot_config_and_the_flag_wins(tmp_path, monkeypatch):
    from tradebot.web.app import load_settings

    monkeypatch.chdir(tmp_path)
    _config(tmp_path, ("XLE",))                              # ./config.yaml loses
    env = tmp_path / "env.yaml"
    env.write_text("symbols: [GLD]\n")
    monkeypatch.setenv("TRADEBOT_CONFIG", str(env))
    settings, source = load_settings(None)
    assert source == str(env) and settings.symbols == ["GLD"]
    flag = tmp_path / "flag.yaml"
    flag.write_text("symbols: [TLT]\n")
    assert load_settings(str(flag))[0].symbols == ["TLT"]
