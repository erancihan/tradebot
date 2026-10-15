"""Web hardening: the same-origin header guard, trusted hosts, the access token."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from .web_client import local_client  # noqa: E402

from tradebot.web.app import create_app  # noqa: E402
from tradebot.web.guard import POST_HEADERS  # noqa: E402

JOB = {"kind": "backtest", "strategy": "sma_crossover", "periods": 120, "seed": 1}


def _app(tmp_path, **kwargs):
    return create_app(trading_db=str(tmp_path / "t.db"), arena_db=str(tmp_path / "a.db"),
                      cache_dir=str(tmp_path / "cache"), **kwargs)


def _client(tmp_path, **kwargs) -> TestClient:
    return local_client(_app(tmp_path, **kwargs))


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
    client = _client(tmp_path, allowed_hosts=["localhost", "pi.lan"])
    assert client.get("/", headers={"Host": "pi.lan:8000"}).status_code == 200
    assert client.get("/", headers={"Host": "evil.example"}).status_code == 400


def test_a_wildcard_disables_the_check_loudly(tmp_path, caplog):
    client = _client(tmp_path, allowed_hosts=["*"])
    assert client.get("/", headers={"Host": "evil.example"}).status_code == 200
    assert "DNS-rebinding" in caplog.text


def test_cli_and_env_extend_the_defaults():
    from tradebot.web.server import allowed_hosts

    hosts = allowed_hosts(["pi.lan", "localhost"], env=" 192.168.1.5 ,,")
    assert hosts == ["localhost", "127.0.0.1", "[::1]", "192.168.1.5", "pi.lan"]


def test_the_test_client_host_is_not_on_the_production_allowlist(tmp_path):
    r = TestClient(_app(tmp_path)).get("/")  # Host: testserver
    assert r.status_code == 400


# --- S3b.3 optional access token --------------------------------------------

TOKEN = "s3cret-phone-token"


def _locked(tmp_path, **kwargs) -> TestClient:
    return local_client(_app(tmp_path, access_token=TOKEN), **kwargs)


def _sign_in(client: TestClient, token: str = TOKEN):
    # A plain form post with no X-Requested-With, exactly what a browser sends.
    return client.post("/login", data={"token": token}, follow_redirects=False)


def _logged_in(tmp_path) -> TestClient:
    client = _locked(tmp_path)
    assert _sign_in(client).status_code == 303
    return client


def _assert_login_headers(r) -> None:
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["referrer-policy"] == "no-referrer"


def test_the_app_is_open_without_a_token(tmp_path):
    client = _client(tmp_path)
    assert client.get("/").status_code == 200
    assert client.get("/login").status_code == 404


def test_without_a_token_post_login_is_still_not_a_page(tmp_path):
    assert _sign_in(_client(tmp_path)).status_code in (404, 405)


def test_a_locked_app_asks_unauthenticated_callers_to_log_in(tmp_path):
    r = _locked(tmp_path).get("/")
    assert r.status_code == 401
    assert "text/html" in r.headers["content-type"]
    assert 'href="/login"' in r.text
    assert TOKEN not in r.text


def test_the_login_page_is_a_password_form_that_posts(tmp_path):
    r = _locked(tmp_path).get("/login")
    assert r.status_code == 200
    assert 'method="post"' in r.text and 'type="password"' in r.text
    assert 'name="token"' in r.text and "<script" not in r.text
    _assert_login_headers(r)


def test_the_sign_in_pages_are_dark_and_thumb_sized_like_the_app(tmp_path):
    # Both pages render before /static is reachable, so the style is inline.
    client = _locked(tmp_path)
    for r in (client.get("/today"), client.get("/login")):
        assert "background:#020617" in r.text and 'name="viewport"' in r.text
    form = client.get("/login").text
    assert "min-height:44px" in form and "{error}" not in form


def test_a_token_in_the_query_string_does_not_log_in(tmp_path):
    r = _locked(tmp_path).get(f"/login?token={TOKEN}", follow_redirects=False)
    assert r.status_code == 200
    assert "set-cookie" not in r.headers


def test_pwa_assets_stay_reachable_before_login(tmp_path):
    client = _locked(tmp_path)
    assert client.get("/app/manifest.webmanifest").status_code == 200
    assert client.get("/static/does-not-exist.js").status_code == 404  # not 401


def test_login_sets_an_httponly_cookie_that_is_not_the_token(tmp_path):
    r = _sign_in(_locked(tmp_path))
    assert r.status_code == 303 and r.headers["location"] == "/"
    _assert_login_headers(r)
    cookie = r.headers["set-cookie"]
    assert cookie.startswith("tradebot_session=")
    assert "HttpOnly" in cookie and "samesite=lax" in cookie.lower()
    assert "Secure" not in cookie
    assert TOKEN not in cookie


def test_login_over_https_marks_the_cookie_secure(tmp_path):
    r = _sign_in(_locked(tmp_path, base_url="https://localhost"))
    assert "Secure" in r.headers["set-cookie"]


def test_a_wrong_token_is_refused_and_sets_nothing(tmp_path):
    r = _sign_in(_locked(tmp_path), token="guess")
    assert r.status_code == 403
    assert "set-cookie" not in r.headers
    assert 'type="password"' in r.text and "not the token" in r.text
    _assert_login_headers(r)


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


def test_post_login_is_the_only_exemption_from_the_header_guard():
    from tradebot.web.guard import EXEMPT

    assert EXEMPT == {("POST", "/login")}


def test_a_logged_in_post_still_needs_the_same_origin_header(tmp_path):
    client = _logged_in(tmp_path)
    assert client.post("/api/jobs", json=JOB).status_code == 403
    assert client.post("/api/jobs", json=JOB, headers=POST_HEADERS).status_code == 200


def test_an_oversized_login_body_is_refused_before_it_is_read(tmp_path):
    client = _locked(tmp_path)
    big = "token=" + "x" * 5000
    r = client.post("/login", content=big,
                    headers={"content-type": "application/x-www-form-urlencoded"})
    assert r.status_code == 413
    assert "set-cookie" not in r.headers


def test_a_login_that_is_not_a_form_is_refused(tmp_path):
    client = _locked(tmp_path)
    r = client.post("/login", json={"token": TOKEN})
    assert r.status_code == 415
    assert "set-cookie" not in r.headers


def _raw_login(app, chunks: list[bytes], content_length: int | None) -> int:
    """Drive the ASGI app directly so the body can disagree with its headers.

    An HTTP client fixes Content-Length up to match what it sends, which is
    exactly the lie these tests need to tell.
    """
    import asyncio

    headers = [(b"host", b"localhost"),
               (b"content-type", b"application/x-www-form-urlencoded")]
    if content_length is None:
        headers.append((b"transfer-encoding", b"chunked"))
    else:
        headers.append((b"content-length", str(content_length).encode()))
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
             "method": "POST", "scheme": "http", "path": "/login", "raw_path": b"/login",
             "root_path": "", "query_string": b"", "headers": headers,
             "client": ("127.0.0.1", 5000), "server": ("localhost", 80)}
    messages = [{"type": "http.request", "body": c, "more_body": i < len(chunks) - 1}
                for i, c in enumerate(chunks)]
    sent: list[dict] = []

    async def receive() -> dict:
        return messages.pop(0) if messages else {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        sent.append(message)

    asyncio.run(app(scope, receive, send))
    return next(m["status"] for m in sent if m["type"] == "http.response.start")


def test_a_chunked_login_body_without_a_length_is_refused(tmp_path):
    app = _app(tmp_path, access_token=TOKEN)
    assert _raw_login(app, [b"token=", TOKEN.encode()], content_length=None) == 413


def test_a_login_body_longer_than_its_declared_length_is_refused(tmp_path):
    app = _app(tmp_path, access_token=TOKEN)
    body = f"token={TOKEN}".encode()
    assert _raw_login(app, [body[:8], body[8:]], content_length=len(body)) == 303
    assert _raw_login(app, [body[:8], body[8:], b"&pad=" + b"x" * 64],
                      content_length=len(body)) == 413
