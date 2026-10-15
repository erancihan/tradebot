"""History's Trades card and /api/history/trades: round trips from fills."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from tradebot.broker import OrderStatus  # noqa: E402
from tradebot.models import Order, Side  # noqa: E402
from tradebot.storage import Storage  # noqa: E402

from .test_web_history import _client, _snapshot  # noqa: E402

T0 = datetime(2026, 10, 15, 14, 30, tzinfo=timezone.utc)


def _fill(st: Storage, symbol: str, side: Side, qty: float, price: float, day: int,
          mode: str = "paper", status: str = "filled", filled: float | None = None) -> None:
    ts = T0 + timedelta(days=day)
    st.record_order(Order(symbol=symbol, qty=qty, side=side, created_at=ts),
                    f"b-{symbol}-{day}-{mode}", mode, price=price)
    oid = st._conn.execute("SELECT max(id) FROM orders").fetchone()[0]
    st.set_order_fill(oid, OrderStatus(status, qty if filled is None else filled, price, ts))


def _seed(tmp_path) -> None:
    with Storage(tmp_path / "t.db") as st:
        _snapshot(st, T0, 10_000.0, "paper")
        _fill(st, "SPY", Side.BUY, 13, 767.24, 0)
        _fill(st, "SPY", Side.SELL, 13, 781.02, 5)                       # +179.14
        _fill(st, "QQQ", Side.BUY, 10, 500.0, 1)
        _fill(st, "QQQ", Side.SELL, 10, 490.0, 2)                        # -100.00
        _fill(st, "IWM", Side.BUY, 10, 200.0, 3, status="partially_filled", filled=4)
        _fill(st, "DIA", Side.BUY, 1, 1.0, 0, mode="dry_run")
        _fill(st, "DIA", Side.SELL, 1, 9.0, 1, mode="dry_run")


def test_the_api_returns_round_trips_summary_and_provenance(tmp_path):
    _seed(tmp_path)
    body = _client(tmp_path).get("/api/history/trades?mode=paper").json()
    assert body["provenance"] == {"mode": "paper", "source": "order log fills", "orders": 5}
    assert [t["symbol"] for t in body["trades"]] == ["SPY", "QQQ"]        # newest close first
    spy = body["trades"][0]
    assert spy["side"] == "long" and spy["qty"] == 13
    assert spy["pnl"] == pytest.approx(179.14)
    assert spy["entry_ts"].startswith("2026-10-15") and spy["exit_ts"].startswith("2026-10-20")
    s = body["summary"]
    assert (s["closed"], s["wins"], s["losses"]) == (2, 1, 1)
    assert s["realised"] == pytest.approx(79.14)
    assert s["profit_factor"] == pytest.approx(1.7914)
    [iwm] = body["open"]                                       # a partial fill: 4 shares
    assert iwm["symbol"] == "IWM" and iwm["qty"] == 4 and iwm["avg_price"] == 200.0


def test_the_api_pins_the_account_and_refuses_an_unknown_one(tmp_path):
    _seed(tmp_path)
    client = _client(tmp_path)
    dry = client.get("/api/history/trades?mode=dry_run").json()
    assert [t["symbol"] for t in dry["trades"]] == ["DIA"] and dry["provenance"]["mode"] == "dry_run"
    assert client.get("/api/history/trades").json()["provenance"]["mode"] == "paper"
    assert client.get("/api/history/trades?mode=bogus").status_code == 400
    assert client.get("/partials/history/trades?mode=bogus").status_code == 400


def test_the_history_page_shows_the_trades_card(tmp_path):
    _seed(tmp_path)
    body = _client(tmp_path).get("/history").text
    assert "data-trades" in body
    assert "2 closed · 1 win" in body and "+$79.14</span> realised" in body
    assert "profit factor 1.8" in body
    spy = body.split('data-trade="SPY"')[1].split("</li>")[0]
    assert "long 13 sh" in spy and "767.24 → 781.02" in spy
    assert "+$179.14 (+1.8%)" in spy and "2026-10-15 → 2026-10-20" in spy
    qqq = body.split('data-trade="QQQ"')[1].split("</li>")[0]
    assert "−$100.00 (-2.0%)" in qqq
    iwm = body.split('data-open-trade="IWM"')[1].split("</li>")[0]
    assert "open since 2026-10-18 at avg 200.00" in iwm and "4 sh" in iwm
    assert "hand trades are not included" in body
    assert 'data-trade="DIA"' not in body                   # the dry-run account stays out


def test_the_trades_partial_renders_the_empty_state(tmp_path):
    body = _client(tmp_path).get("/partials/history/trades?mode=paper").text
    assert "No closed trades yet. A trade closes when a name goes back to flat." in body
    assert "data-trade=" not in body and "0 filled orders" in body


def test_the_trades_partial_follows_the_pinned_account(tmp_path):
    _seed(tmp_path)
    body = _client(tmp_path).get("/partials/history/trades?mode=dry_run").text
    assert 'data-trade="DIA"' in body and 'data-trade="SPY"' not in body
    assert "(dry_run)" in body
