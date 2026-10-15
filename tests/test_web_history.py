"""History page: performance, the merged order/proposal timeline, its pages."""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from .web_client import local_client  # noqa: E402

from tradebot.models import Order, Side  # noqa: E402
from tradebot.storage import Storage  # noqa: E402
from tradebot.web.app import create_app  # noqa: E402
from tradebot.web.repository import TradingRepository  # noqa: E402
from tradebot.web.services import history_service  # noqa: E402

from .test_advisor import _line, dummy_proposal  # noqa: E402
from .test_storage import _OLD_ORDERS  # noqa: E402

T0 = datetime(2026, 10, 1, 14, 30, tzinfo=timezone.utc)


def _client(tmp_path, mode: str = "paper") -> TestClient:
    config = tmp_path / "config.yaml"
    config.write_text(f"mode: {mode}\nsymbols: [SPY, QQQ]\n")
    return local_client(create_app(trading_db=str(tmp_path / "t.db"),
                                   arena_db=str(tmp_path / "a.db"),
                                   cache_dir=str(tmp_path / "cache"),
                                   settings_path=str(config)))


def _snapshot(st: Storage, ts: datetime, equity: float, mode: str) -> None:
    st._conn.execute("INSERT INTO equity_snapshots (ts, equity, cash, mode)"
                     " VALUES (?, ?, ?, ?)", (ts.isoformat(), equity, 1_000.0, mode))
    st._conn.commit()


def _order(st: Storage, symbol: str, qty: float, ts: datetime, mode: str = "paper",
           price: float | None = None, side: Side = Side.BUY) -> None:
    st.record_order(Order(symbol=symbol, qty=qty, side=side, created_at=ts),
                    None, mode, price=price)


def _seed(tmp_path) -> None:
    with Storage(tmp_path / "t.db") as st:
        _snapshot(st, T0 - timedelta(days=9), 5_000.0, "dry_run")
        _snapshot(st, T0, 10_000.0, "paper")
        _snapshot(st, T0 + timedelta(days=2), 10_500.0, "paper")
        _order(st, "SPY", 10, T0 + timedelta(hours=1), price=401.5)
        _order(st, "IWM", 3, T0 + timedelta(hours=3))                   # no price known
        _order(st, "DIA", 7, T0 + timedelta(hours=2), mode="dry_run", price=1.0)
        batch = st.record_proposal(dummy_proposal(created_at=T0 + timedelta(hours=2),
                                                  lines=[_line(), _line("QQQ", "hold", 0.0)]),
                                   "paper", status="pending", hold_status="suggested")
        st.set_line_status([ln["id"] for ln in st.pending_lines("paper")], "submitted")
        st.record_proposal(dummy_proposal(created_at=T0, lines=[_line("XLE")]), "dry_run")
        assert batch


def _events(body: str) -> list[str]:
    return re.findall(r'data-event="(\w+)"', body)


def test_the_history_page_says_plainly_when_nothing_is_recorded(tmp_path):
    body = _client(tmp_path).get("/history").text
    assert "data-empty" in body and "data-no-snapshots" in body
    assert "No equity snapshots for paper yet" in body
    assert 'href="/history"' in body and 'aria-current="page"' in body
    assert "data-show-more" in body and 'data-next=""' in body
    assert "data-equity-chart" not in body


def test_the_history_page_shows_performance_and_one_timeline(tmp_path):
    _seed(tmp_path)
    body = _client(tmp_path).get("/history").text
    assert "$10,500.00" in body and "+$500.00" in body and "(+5.00%)" in body
    assert "data-equity-chart" in body
    # Newest first, orders and the proposal batch merged by time.
    assert _events(body) == ["order", "proposal", "order"]
    assert re.findall(r'data-symbol="(\w+)"', body) == ["IWM", "SPY"]
    assert "10 sh · $4,015.00" in body                 # sized price x qty
    iwm = body.split('data-symbol="IWM"')[1].split("</li>")[0]
    assert "3 sh" in iwm and "$" not in iwm             # no price: the quantity only
    assert "1 trade:" in body and "1 submitted" in body and "1 hold" in body
    assert "sma_crossover signals long; buy." in body   # the reason, behind the tap
    assert "DIA" not in body and "XLE" not in body       # the dry-run account stays out


def test_history_falls_back_to_the_configured_mode_before_any_snapshot(tmp_path):
    with Storage(tmp_path / "t.db") as st:
        _order(st, "SPY", 1, T0, mode="paper", price=10.0)
        _order(st, "DIA", 1, T0, mode="dry_run", price=10.0)
    body = _client(tmp_path, mode="paper").get("/history").text
    assert 'data-symbol="SPY"' in body and "DIA" not in body


def test_show_more_walks_every_event_once_and_stops(tmp_path):
    with Storage(tmp_path / "t.db") as st:
        _snapshot(st, T0, 10_000.0, "paper")
        for i in range(27):                           # orders on even hours
            _order(st, f"O{i:02d}", 1, T0 + timedelta(hours=2 * i), price=10.0)
        for i in range(18):                           # batches on odd hours
            st.record_proposal(dummy_proposal(created_at=T0 + timedelta(hours=2 * i + 1),
                                              lines=[_line(f"B{i:02d}")]), "paper")
    client = _client(tmp_path)
    page = client.get("/history").text
    seen = re.findall(r'datetime="([^"]+)"', page)
    url = re.search(r'data-next="([^"]*)"', page).group(1).replace("&amp;", "&")
    fetched = 0
    while url:
        resp = client.get(url)
        assert resp.status_code == 200
        assert "data-empty" not in resp.text           # a later page is never "empty"
        seen += re.findall(r'datetime="([^"]+)"', resp.text)
        url = resp.headers["X-History-Next"]
        fetched += 1
    assert fetched == 2                                 # 45 events at 20 a page
    assert len(seen) == 45 and len(set(seen)) == 45     # nothing skipped or repeated
    assert seen == sorted(seen, reverse=True)           # newest first across pages


def test_the_first_page_partial_matches_the_page(tmp_path):
    _seed(tmp_path)
    client = _client(tmp_path)
    resp = client.get("/partials/history")
    assert _events(resp.text) == ["order", "proposal", "order"]
    assert resp.headers["X-History-Next"] == ""
    perf = client.get("/partials/history/performance").text
    assert "+$500.00" in perf


def test_an_order_log_from_before_the_price_column_still_renders(tmp_path):
    """The web reader is read-only and never migrates: an old log shows qty only."""
    db = tmp_path / "t.db"
    con = sqlite3.connect(db)
    con.execute(_OLD_ORDERS)
    con.execute("INSERT INTO orders (ts, symbol, side, qty, type, broker_order_id, mode)"
                " VALUES (?, 'SPY', 'sell', 4, 'market', NULL, 'paper')", (T0.isoformat(),))
    con.commit()
    con.close()
    body = _client(tmp_path).get("/history").text
    assert 'data-symbol="SPY"' in body and "4 sh" in body


def test_events_page_cursor_only_moves_past_shown_rows(tmp_path):
    with Storage(tmp_path / "t.db") as st:
        for i in range(3):
            _order(st, f"O{i}", 1, T0 + timedelta(days=10 + i), price=1.0)
        st.record_proposal(dummy_proposal(created_at=T0), "paper")
    repo = TradingRepository(str(tmp_path / "t.db"))
    first = history_service.events_page(repo, "paper", limit=2)
    assert [e["symbol"] for e in first["events"]] == ["O2", "O1"]
    # No batch was shown, so the batch cursor stays unset and the batch comes next.
    o1 = first["events"][-1]
    assert first["next"] == history_service.next_url({"order": (o1["ts"], o1["id"])}, "paper")
    assert "batch" not in first["next"]
    second = history_service.events_page(repo, "paper", before_order=(o1["ts"], o1["id"]),
                                         limit=2)
    assert [e["kind"] for e in second["events"]] == ["order", "proposal"]
    assert second["next"] is None


def _walk(client, url: str) -> list[str]:
    """Every event key the pages serve, following ``X-History-Next`` from ``url``."""
    seen: list[str] = []
    while url:
        resp = client.get(url)
        assert resp.status_code == 200
        seen += re.findall(r'data-(?:symbol|batch)="(\w+)"', resp.text)
        url = resp.headers["X-History-Next"]
    return seen


def test_show_more_pages_on_time_when_ids_and_times_disagree(tmp_path, monkeypatch):
    """Two replay runs restart the clock: ids rise while times go d1 d2 d3 d1 d2 d3.
    Paging on ids alone skipped rows; the (ts, id) keyset shows each exactly once."""
    monkeypatch.setattr(history_service, "PAGE_SIZE", 2)
    days = [T0 + timedelta(days=d) for d in (0, 1, 2, 0, 1, 2)]
    with Storage(tmp_path / "t.db") as st:
        _snapshot(st, T0, 10_000.0, "paper")
        for i, day in enumerate(days):
            st.record_proposal(dummy_proposal(created_at=day, lines=[_line()]), "paper")
            _order(st, f"O{i}", 1, day + timedelta(hours=1), price=1.0)
    seen = _walk(_client(tmp_path), "/partials/history")
    batches = [k for k in seen if k.isdigit()]
    orders = [k for k in seen if k.startswith("O")]
    assert sorted(batches) == ["1", "2", "3", "4", "5", "6"]
    assert sorted(orders) == [f"O{i}" for i in range(6)]
    assert len(seen) == 12


def test_the_account_stays_put_between_page_load_and_show_more(tmp_path, monkeypatch):
    """A dry-run snapshot written after the page loaded makes dry_run the
    newest account, but Show more and the poll keep serving the page's."""
    monkeypatch.setattr(history_service, "PAGE_SIZE", 1)
    with Storage(tmp_path / "t.db") as st:
        _snapshot(st, T0, 10_000.0, "paper")
        _order(st, "SPY", 1, T0, price=1.0)
        _order(st, "QQQ", 1, T0 + timedelta(hours=1), price=1.0)
        _order(st, "DIA", 1, T0, mode="dry_run", price=1.0)
        _order(st, "IWM", 1, T0 + timedelta(hours=1), mode="dry_run", price=1.0)
    client = _client(tmp_path)
    page = client.get("/history").text
    url = re.search(r'data-next="([^"]*)"', page).group(1).replace("&amp;", "&")
    assert "mode=paper" in url
    with Storage(tmp_path / "t.db") as st:
        _snapshot(st, T0 + timedelta(days=1), 5_000.0, "dry_run")
    assert re.findall(r'data-symbol="(\w+)"', client.get(url).text) == ["SPY"]
    fresh = client.get("/partials/history?mode=paper").text
    assert re.findall(r'data-symbol="(\w+)"', fresh) == ["QQQ"]
    perf = client.get("/partials/history/performance?mode=paper").text
    assert "$10,000.00" in perf and "5,000" not in perf
    assert client.get("/partials/history?mode=bogus").status_code == 400
