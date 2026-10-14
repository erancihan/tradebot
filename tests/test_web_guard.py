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


# --- S3b.2 trusted hosts ----------------------------------------------------

def test_a_foreign_host_header_is_refused(tmp_path):
    r = _client(tmp_path).get("/", headers={"Host": "evil.example"})
    assert r.status_code == 400


@pytest.mark.parametrize("host", ["localhost:8000", "127.0.0.1", "[::1]:8000"])
def test_loopback_hosts_are_served_by_default(tmp_path, host):
    assert _client(tmp_path).get("/api/strategies", headers={"Host": host}).status_code == 200


def test_an_allowed_host_is_served(tmp_path):
    client = _client(tmp_path, allowed_hosts=["testserver", "pi.lan"])
    assert client.get("/", headers={"Host": "pi.lan:8000"}).status_code == 200
    assert client.get("/", headers={"Host": "evil.example"}).status_code == 400


def test_a_wildcard_disables_the_check_loudly(tmp_path, caplog):
    client = _client(tmp_path, allowed_hosts=["*"])
    assert client.get("/", headers={"Host": "evil.example"}).status_code == 200
    assert "DNS-rebinding" in caplog.text


def test_cli_and_env_extend_the_defaults():
    from tradebot.web.server import allowed_hosts

    hosts = allowed_hosts(["pi.lan", "localhost"], env=" 192.168.1.5 ,,")
    assert hosts[:4] == ["localhost", "127.0.0.1", "[::1]", "testserver"]
    assert hosts[4:] == ["192.168.1.5", "pi.lan"]


# --- S3b.3 optional access token --------------------------------------------

TOKEN = "s3cret-phone-token"


def _locked(tmp_path, **kwargs) -> TestClient:
    return TestClient(_app(tmp_path, access_token=TOKEN), **kwargs)


def _logged_in(tmp_path) -> TestClient:
    client = _locked(tmp_path)
    assert client.get(f"/login?token={TOKEN}", follow_redirects=False).status_code == 303
    return client


def test_the_app_is_open_without_a_token(tmp_path):
    client = _client(tmp_path)
    assert client.get("/").status_code == 200
    assert client.get("/login?token=x").status_code == 404


def test_a_locked_app_asks_unauthenticated_callers_to_log_in(tmp_path):
    r = _locked(tmp_path).get("/")
    assert r.status_code == 401
    assert "text/html" in r.headers["content-type"]
    assert "/login?token=" in r.text


def test_pwa_assets_stay_reachable_before_login(tmp_path):
    client = _locked(tmp_path)
    assert client.get("/app/manifest.webmanifest").status_code == 200
    assert client.get("/static/does-not-exist.js").status_code == 404  # not 401


def test_login_sets_an_httponly_cookie_that_is_not_the_token(tmp_path):
    r = _locked(tmp_path).get(f"/login?token={TOKEN}", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"
    cookie = r.headers["set-cookie"]
    assert cookie.startswith("tradebot_session=")
    assert "HttpOnly" in cookie and "samesite=lax" in cookie.lower()
    assert "Secure" not in cookie
    assert TOKEN not in cookie


def test_login_over_https_marks_the_cookie_secure(tmp_path):
    client = _locked(tmp_path, base_url="https://testserver")
    r = client.get(f"/login?token={TOKEN}", follow_redirects=False)
    assert "Secure" in r.headers["set-cookie"]


def test_a_wrong_token_is_refused_and_sets_nothing(tmp_path):
    r = _locked(tmp_path).get("/login?token=guess", follow_redirects=False)
    assert r.status_code == 403
    assert "set-cookie" not in r.headers


def test_the_cookie_unlocks_pages_and_the_event_stream(tmp_path):
    client = _logged_in(tmp_path)
    assert client.get("/").status_code == 200
    r = client.get("/sse/dashboard?limit=1&interval=0")
    assert r.status_code == 200
    assert "event: account" in r.text


def test_the_event_stream_is_locked_too(tmp_path):
    assert _locked(tmp_path).get("/sse/dashboard?limit=1&interval=0").status_code == 401


def test_the_raw_token_is_not_a_valid_cookie(tmp_path):
    client = _locked(tmp_path, cookies={"tradebot_session": TOKEN})
    assert client.get("/").status_code == 401


def test_a_bearer_header_works_without_a_cookie(tmp_path):
    client = _locked(tmp_path)
    ok = client.get("/api/strategies", headers={"Authorization": f"Bearer {TOKEN}"})
    assert ok.status_code == 200
    bad = client.get("/api/strategies", headers={"Authorization": "Bearer nope"})
    assert bad.status_code == 401


def test_a_logged_in_post_still_needs_the_same_origin_header(tmp_path):
    client = _logged_in(tmp_path)
    assert client.post("/api/jobs", json=JOB).status_code == 403
    assert client.post("/api/jobs", json=JOB, headers=POST_HEADERS).status_code == 200
