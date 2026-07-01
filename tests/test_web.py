from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from tradebot.arena.scenario import Scenario  # noqa: E402
from tradebot.arena.store import ArenaStore  # noqa: E402
from tradebot.arena.tournament import run_tournament  # noqa: E402
from tradebot.models import Order, Side  # noqa: E402
from tradebot.storage import Storage  # noqa: E402
from tradebot.web.app import create_app  # noqa: E402

ALGOS = Path(__file__).resolve().parents[1] / "algos"


def _seed_trading(path):
    from tradebot.data.synthetic import synthetic_ohlcv

    st = Storage(str(path))
    st.record_equity(10_000, 5_000, "paper")
    st.record_equity(10_100, 4_900, "paper")
    st.record_equity(10_050, 4_950, "paper")
    st.record_order(Order(symbol="SPY", qty=10, side=Side.BUY), "ord-1", "paper")
    st.record_bars("SPY", "1day", synthetic_ohlcv(periods=20, seed=1), "paper")
    st.close()


def _seed_arena(path):
    scenario = Scenario(name="t", periods=120, seed=1)
    outcome = run_tournament([str(ALGOS)], scenario, "total_return")
    with ArenaStore(str(path)) as store:
        store.record_run(scenario, "total_return", outcome)


def _seed_season(path):
    from tradebot.arena.season import (
        ReplaySeasonFeed,
        Season,
        SeasonConfig,
        SeasonStore,
        run_season,
    )
    from tradebot.data.synthetic import synthetic_ohlcv

    with SeasonStore(str(path)) as store:
        season = Season.create(store, SeasonConfig(
            name="wk", symbols=["DEMO"], metric="total_return", algo_paths=[str(ALGOS)]))
        run_season(season, ReplaySeasonFeed({"DEMO": synthetic_ohlcv(periods=20, seed=1)}),
                   max_ticks=10)


@pytest.fixture
def client(tmp_path):
    _seed_trading(tmp_path / "tradebot.db")
    _seed_arena(tmp_path / "arena.db")
    _seed_season(tmp_path / "season.db")
    app = create_app(trading_db=str(tmp_path / "tradebot.db"),
                     arena_db=str(tmp_path / "arena.db"),
                     season_db=str(tmp_path / "season.db"))
    return TestClient(app)


def test_dashboard_renders(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Dashboard" in r.text
    assert "Equity curve" in r.text
    assert "SPY" in r.text                      # order rendered server-side


def test_equity_api_returns_chronological_points(client):
    data = client.get("/api/equity").json()
    assert len(data["points"]) == 3
    assert data["points"][0]["equity"] == 10_000.0
    assert data["points"][-1]["equity"] == 10_050.0


def test_equity_api_mode_filter(client):
    assert len(client.get("/api/equity?mode=paper").json()["points"]) == 3
    assert client.get("/api/equity?mode=live").json()["points"] == []


def test_orders_api(client):
    rows = client.get("/api/orders").json()
    assert any(r["symbol"] == "SPY" and r["side"] == "buy" for r in rows)


def test_sse_dashboard_streams_account(client):
    r = client.get("/sse/dashboard?limit=1&interval=0")
    assert r.status_code == 200
    assert "text/event-stream" in r.headers["content-type"]
    assert "event: account" in r.text
    assert '"source"' in r.text          # account snapshot JSON is present


def test_account_api(client):
    a = client.get("/api/account").json()
    # No creds in tests -> falls back to the local snapshot from the SQLite log.
    assert a["source"] == "local"
    assert a["equity"] == 10_050.0
    assert "positions" in a


def test_symbols_and_bars_api(client):
    assert "SPY" in client.get("/api/symbols").json()
    data = client.get("/api/bars?symbol=SPY").json()
    assert data["symbol"] == "SPY"
    assert len(data["candles"]) == 20
    assert {"ts", "open", "high", "low", "close", "volume"} <= set(data["candles"][0])


def test_chart_page_renders(client):
    r = client.get("/chart")
    assert r.status_code == 200
    assert "Price chart" in r.text and "candleChart(" in r.text


def test_partials_reuse_components(client):
    assert "SPY" in client.get("/partials/orders").text
    assert "Total return" in client.get("/partials/stats").text
    assert client.get("/partials/positions").status_code == 200


def test_arena_page_and_api(client):
    page = client.get("/arena")
    assert page.status_code == 200
    assert "buy_and_hold" in page.text and "Equity curves" in page.text

    runs = client.get("/api/arena/runs").json()
    assert len(runs) >= 1
    detail = client.get(f"/api/arena/runs/{runs[0]['id']}").json()
    assert len(detail["entries"]) == 3
    assert detail["curves"] and detail["curves"][0]["equity"]


def test_seasons_api(client):
    seasons = client.get("/api/seasons").json()
    assert len(seasons) >= 1
    detail = client.get(f"/api/seasons/{seasons[0]['id']}").json()
    assert len(detail["latest"]) == 3
    assert detail["curves"] and len(detail["curves"][0]["total_return"]) >= 1


def test_seasons_page_renders(client):
    r = client.get("/seasons")
    assert r.status_code == 200
    assert "Seasons" in r.text and "seasonChart(" in r.text


def test_empty_databases_render_gracefully(tmp_path):
    app = create_app(trading_db=str(tmp_path / "missing.db"),
                     arena_db=str(tmp_path / "missing2.db"))
    c = TestClient(app)
    assert c.get("/").status_code == 200
    assert c.get("/arena").status_code == 200
    assert c.get("/api/equity").json()["points"] == []
    assert c.get("/api/arena/runs").json() == []
