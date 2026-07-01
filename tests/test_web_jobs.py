import time

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from tradebot.web.app import create_app  # noqa: E402


def _client(tmp_path):
    return TestClient(create_app(trading_db=str(tmp_path / "t.db"),
                                 arena_db=str(tmp_path / "a.db")))


def _wait(client, job_id, timeout=15.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["state"] in ("done", "error"):
            return job
        time.sleep(0.05)
    raise AssertionError("job did not finish in time")


def test_backtest_job_runs_to_completion(tmp_path):
    client = _client(tmp_path)
    r = client.post("/api/jobs", json={
        "kind": "backtest", "strategy": "sma_crossover", "periods": 200,
        "seed": 1, "initial_cash": 10000, "params": {"fast": 5, "slow": 20},
    })
    assert r.status_code == 200
    job = _wait(client, r.json()["job_id"])
    assert job["state"] == "done"
    assert "total_return" in job["summary"]
    assert len(job["equity"]["equity"]) > 0


def test_dryrun_job_produces_equity_curve(tmp_path):
    client = _client(tmp_path)
    r = client.post("/api/jobs", json={
        "kind": "dryrun", "strategy": "rsi_reversion", "periods": 150,
        "seed": 2, "initial_cash": 10000, "params": {"period": 14, "oversold": 30},
    })
    job = _wait(client, r.json()["job_id"])
    assert job["state"] == "done"
    assert "final_equity" in job["summary"]
    assert len(job["equity"]["index"]) == len(job["equity"]["equity"]) > 0


def test_invalid_kind_is_rejected(tmp_path):
    assert _client(tmp_path).post("/api/jobs", json={"kind": "nope"}).status_code == 400


def test_unknown_job_is_404(tmp_path):
    assert _client(tmp_path).get("/api/jobs/doesnotexist").status_code == 404


def test_bad_strategy_job_reports_error(tmp_path):
    client = _client(tmp_path)
    r = client.post("/api/jobs", json={"kind": "backtest", "strategy": "no_such_strategy"})
    job = _wait(client, r.json()["job_id"])
    assert job["state"] == "error"
    assert job["error"]


def test_run_page_renders(tmp_path):
    r = _client(tmp_path).get("/run")
    assert r.status_code == 200
    assert "Run a simulation" in r.text
