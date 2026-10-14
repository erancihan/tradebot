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
    r = client.post("/api/whatif", json={"symbols": ["DEMO"], "source": "synthetic",
                                         "initial_cash": 10000, "monthly_contribution": 200})
    assert r.status_code == 200
    job = _wait(client, r.json()["job_id"])
    assert job["state"] == "done", job.get("error")
    assert job["kind"] == "whatif"
    assert job["provenance"]
    assert job["summary"]


@pytest.mark.parametrize("body", [
    {"symbols": []},
    {"symbols": ["SPY"], "source": "nope"},
    {"symbols": ["SPY"], "initial_cash": 0},
    {"symbols": ["SPY"], "monthly_contribution": -5},
])
def test_whatif_rejects_an_impossible_plan(tmp_path, body):
    assert _client(tmp_path).post("/api/whatif", json=body).status_code == 400
