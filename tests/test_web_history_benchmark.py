"""History against holding the list: the card's alpha cell and the chart's line."""

from __future__ import annotations

from datetime import timedelta

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from tradebot.data.cache import BarCache  # noqa: E402
from tradebot.storage import Storage  # noqa: E402

from .test_history_benchmark import _bars  # noqa: E402
from .test_web_history import T0, _client, _snapshot  # noqa: E402


def _seed(tmp_path, *, bars: bool = True) -> None:
    with Storage(tmp_path / "t.db") as st:
        _snapshot(st, T0, 10_000.0, "paper")                     # Thu Oct 1, 14:30
        _snapshot(st, T0 + timedelta(days=2), 10_500.0, "paper")  # Sat Oct 3
    if bars:
        cache = BarCache(tmp_path / "cache")
        cache.store("SPY", "1day", _bars([100.0, 102.0, 104.0]))   # Oct 1, 2, 5
        cache.store("QQQ", "1day", _bars([50.0, 51.0, 52.0]))


def test_equity_api_carries_the_benchmark_with_its_provenance(tmp_path):
    # The first snapshot (Oct 1, 14:30) is before Oct 1's close; Sep 30 is not
    # cached, so the list is bought at the next session's close, Oct 1.
    _seed(tmp_path)
    data = _client(tmp_path).get("/api/equity?mode=paper").json()
    assert len(data["points"]) == 2 and data["points"][0]["equity"] == 10_000.0
    assert data["benchmark"] == [{"ts": "2026-10-01", "value": 10_000.0},
                                 {"ts": "2026-10-02", "value": pytest.approx(10_200.0)}]
    assert data["benchmark_symbols"] == ["SPY", "QQQ"]
    assert data["benchmark_since"] == "2026-10-01" and data["benchmark_until"] == "2026-10-02"
    assert data["benchmark_source"] == "cache" and data["benchmark_note"] is None


def test_mixed_accounts_have_no_benchmark_until_one_is_picked(tmp_path):
    _seed(tmp_path)
    with Storage(tmp_path / "t.db") as st:
        _snapshot(st, T0 + timedelta(hours=1), 3_000.0, "dry_run")
    client = _client(tmp_path)
    mixed = client.get("/api/equity").json()
    assert len(mixed["points"]) == 3
    assert mixed["benchmark"] is None
    assert mixed["benchmark_note"] == "pick one account to compare"
    paper = client.get("/api/equity?mode=paper").json()
    assert paper["benchmark"] is not None and paper["benchmark_note"] is None


def test_equity_api_without_bars_says_why(tmp_path):
    _seed(tmp_path, bars=False)
    data = _client(tmp_path).get("/api/equity?mode=paper").json()
    assert len(data["points"]) == 2
    assert data["benchmark"] is None
    assert data["benchmark_note"] == "no cached daily bars for SPY, QQQ"


def test_equity_api_without_snapshots_has_no_benchmark(tmp_path):
    data = _client(tmp_path).get("/api/equity?mode=paper").json()
    assert data["points"] == [] and data["benchmark"] is None


def test_the_watchlist_is_the_list_held(tmp_path):
    _seed(tmp_path)
    with Storage(tmp_path / "t.db") as st:
        st.add_to_watchlist(["SPY"])
    data = _client(tmp_path).get("/api/equity?mode=paper").json()
    assert data["benchmark_symbols"] == ["SPY"]


def test_the_card_shows_alpha_against_holding_the_list(tmp_path):
    _seed(tmp_path)
    client = _client(tmp_path)
    for body in (client.get("/history").text,
                 client.get("/partials/history/performance?mode=paper").text):
        assert "vs holding the list" in body and "data-alpha" in body
        alpha = body.split("data-alpha>")[1].split("</div>")[0].strip()
        assert alpha == "+3.00%"                           # +5% against +2%
        assert "text-emerald-400\" data-alpha" in body
        assert "Equal-weight SPY, QQQ since 2026-10-01" in body
        assert "through 2026-10-02" in body
        assert "cached closes" in body and "data-no-benchmark" not in body
        basis = " ".join(body.split("data-benchmark-basis>")[1].split("</div>")[0].split())
        # Two short lines on a phone: what is held, then both returns.
        assert basis.count("<p>") == 2
        assert "today's list +2.00% · account +5.00%" in basis


def test_the_card_names_the_pull_command_without_bars(tmp_path):
    _seed(tmp_path, bars=False)
    body = _client(tmp_path).get("/partials/history/performance?mode=paper").text
    assert "data-no-benchmark" in body and "data-alpha" not in body
    assert "no cached daily bars for SPY, QQQ" in body
    assert "tradebot data pull --symbols SPY QQQ --timeframe 1day" in body


def test_a_long_list_is_shortened_never_truncated(tmp_path):
    _seed(tmp_path)
    names = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG", "HHH"]
    cache = BarCache(tmp_path / "cache")
    for name in names:
        cache.store(name, "1day", _bars([10.0, 10.0]))
    with Storage(tmp_path / "t.db") as st:
        st.add_to_watchlist(names)
    body = _client(tmp_path).get("/partials/history/performance?mode=paper").text
    assert "Equal-weight AAA, BBB, CCC, DDD, EEE, FFF +2 more since" in body
