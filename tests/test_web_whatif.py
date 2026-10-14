"""The What-if page and its job: plan in, both curves and provenance out."""

import time

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from tradebot.web.app import create_app  # noqa: E402


def _client(tmp_path):
    return TestClient(create_app(trading_db=str(tmp_path / "t.db"),
                                 arena_db=str(tmp_path / "a.db"),
                                 cache_dir=str(tmp_path / "cache")))


def _wait(client, job_id, timeout=20.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["state"] in ("done", "error"):
            return job
        time.sleep(0.05)
    raise AssertionError("job did not finish in time")


def _seed_cache(tmp_path, symbols=("AAA", "BBB"), periods=300):
    """Real-shaped frames in the app's bar cache, manifests included."""
    from tradebot.data.cache import BarCache
    from tradebot.data.synthetic import synthetic_ohlcv

    cache = BarCache(tmp_path / "cache")
    for i, sym in enumerate(symbols):
        df = synthetic_ohlcv(periods=periods, seed=10 + i, freq="B", start="2022-01-03")
        cache.store(sym, "1day", df)
        cache.record_coverage(sym, "1day", df.index.min(), df.index.max())
    return df


def test_whatif_page_renders_with_one_primary_button(tmp_path):
    text = _client(tmp_path).get("/whatif").text
    assert 'x-data="whatIf()"' in text
    assert "Run what-if" in text
    assert "data-result-card" in text


def test_whatif_is_a_bottom_tab_and_chart_moved_under_more(tmp_path):
    body = _client(tmp_path).get("/").text
    tabbar = body[body.index("data-tabbar"):]
    tabs = tabbar[tabbar.index('class="flex items-stretch"'):]
    assert 'href="/whatif"' in tabs
    assert 'href="/chart"' not in tabs           # Chart lives in the More sheet now
    assert 'href="/chart"' in tabbar


def test_whatif_job_returns_a_result_with_provenance(tmp_path):
    client = _client(tmp_path)
    r = client.post("/api/whatif", json={"symbols": ["DEMO", "TOY"], "source": "synthetic",
                                         "start": "2021-01-04", "end": "2022-12-30",
                                         "initial_cash": 10000, "monthly_contribution": 200})
    assert r.status_code == 200
    job = _wait(client, r.json()["job_id"])
    assert job["state"] == "done", job.get("error")
    assert job["kind"] == "whatif"
    assert job["provenance"]["source"] == "synthetic"
    assert "invented" in job["provenance"]["note"]
    assert job["summary"]["contributions"] == 10000 + 23 * 200
    assert len(job["equity"]["equity"]) == job["provenance"]["bars"]


def test_whatif_job_runs_from_the_cache_and_carries_provenance(tmp_path):
    _seed_cache(tmp_path)
    client = _client(tmp_path)
    r = client.post("/api/whatif", json={"symbols": ["aaa", "BBB"], "start": "2022-02-01",
                                         "initial_cash": 5000, "monthly_contribution": 100})
    job = _wait(client, r.json()["job_id"])
    assert job["state"] == "done", job.get("error")
    prov = job["provenance"]
    assert prov["source"] == "real" and prov["symbol"] == "AAA,BBB"
    assert prov["start"].startswith("2022-02-01")
    s = job["summary"]
    assert s["gain"] == pytest.approx(s["final_value"] - s["contributions"], abs=0.02)


def test_whatif_uncached_range_returns_pull_hint(tmp_path):
    _seed_cache(tmp_path, symbols=("AAA",))
    client = _client(tmp_path)
    r = client.post("/api/whatif", json={"symbols": ["AAA", "ZZZ", "YYY"],
                                         "start": "2022-02-01", "end": "2022-06-01"})
    job = _wait(client, r.json()["job_id"])
    assert job["state"] == "error"
    assert ("tradebot data pull --symbols ZZZ YYY --timeframe 1day "
            "--start 2022-02-01 --end 2022-06-01") in job["error"]


@pytest.mark.parametrize("body", [
    {"symbols": []},
    {"symbols": ["SPY"], "source": "nope"},
    {"symbols": ["SPY"], "initial_cash": 0},
    {"symbols": ["SPY"], "monthly_contribution": -5},
])
def test_whatif_rejects_an_impossible_plan(tmp_path, body):
    assert _client(tmp_path).post("/api/whatif", json=body).status_code == 400
