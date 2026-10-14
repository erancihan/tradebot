"""Web hardening: the same-origin header guard, trusted hosts, the access token."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from tradebot.web.app import create_app  # noqa: E402
from tradebot.web.guard import POST_HEADERS  # noqa: E402

JOB = {"kind": "backtest", "strategy": "sma_crossover", "periods": 120, "seed": 1}


def _app(tmp_path, **kwargs):
    return create_app(trading_db=str(tmp_path / "t.db"), arena_db=str(tmp_path / "a.db"),
                      cache_dir=str(tmp_path / "cache"), **kwargs)


def _client(tmp_path, **kwargs) -> TestClient:
    return TestClient(_app(tmp_path, **kwargs))


# --- S3b.1 same-origin guard ------------------------------------------------

def test_a_post_without_the_header_is_refused(tmp_path):
    r = _client(tmp_path).post("/api/jobs", json=JOB)
    assert r.status_code == 403
    assert r.json() == {"detail": "missing X-Requested-With header"}


def test_a_post_with_the_wrong_header_value_is_refused(tmp_path):
    r = _client(tmp_path).post("/api/jobs", json=JOB,
                               headers={"X-Requested-With": "XMLHttpRequest"})
    assert r.status_code == 403


def test_a_post_with_the_header_goes_through(tmp_path):
    r = _client(tmp_path).post("/api/jobs", json=JOB, headers=POST_HEADERS)
    assert r.status_code == 200
    assert "job_id" in r.json()


@pytest.mark.parametrize("method", ["put", "patch", "delete"])
def test_every_mutating_method_is_guarded(tmp_path, method):
    r = getattr(_client(tmp_path), method)("/api/jobs")
    assert r.status_code == 403


def test_reads_need_no_header(tmp_path):
    client = _client(tmp_path)
    assert client.get("/api/strategies").status_code == 200
    assert client.get("/").status_code == 200
