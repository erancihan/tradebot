"""The phone push's Approve all / Skip buttons, end to end over a dry-run.

The links are taken from the ntfy request the pass really sends (``urlopen``
faked), then POSTed the way ntfy does: the guard header, no cookie.
"""

from __future__ import annotations

from urllib.parse import urlsplit
from unittest.mock import patch

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from tradebot.autopilot import Autopilot  # noqa: E402
from tradebot.web.app import create_app  # noqa: E402
from tradebot.web.guard import POST_HEADERS  # noqa: E402
from tradebot.web.services import autopilot_service  # noqa: E402
from tests.test_web_autopilot import _seed_cache  # noqa: E402
from tests.web_client import local_client  # noqa: E402

PUBLIC = "http://192.168.1.20:8000"


@pytest.fixture(autouse=True)
def _no_credentials(monkeypatch):
    for key in ("ALPACA_API_KEY", "ALPACA_API_SECRET"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr("tradebot.config.AlpacaCredentials.from_env", lambda: None)


class _Resp:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def pushes(monkeypatch):
    got: list = []
    monkeypatch.setattr("tradebot.notify.urllib.request.urlopen",
                        lambda req, timeout=None: (got.append(req), _Resp())[1])
    return got


def _app(tmp_path, token=None):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("mode: paper\nsymbols: [SPY, QQQ]\nstrategy:\n  name: buy_and_hold\n"
                   f"notify:\n  ntfy_topic: t0pic\n  public_url: {PUBLIC}\n")
    return create_app(trading_db=str(tmp_path / "t.db"), arena_db=str(tmp_path / "a.db"),
                      cache_dir=str(tmp_path / "cache"), settings_path=str(cfg),
                      access_token=token)


def _pass(app, client):
    with patch.object(Autopilot, "start", lambda self: False):
        pilot = autopilot_service.get(app)
        pilot.set_mode("approve")
    pilot.is_open = lambda now: True
    pilot.tick()
    return pilot


def _links(push) -> dict[str, str]:
    """verb -> path?query, from the push's Actions header."""
    out = {}
    for action in push.get_header("Actions").split("; "):
        kind, label, url = (p.strip() for p in action.split(", ")[:3])
        url = url.strip('"')
        assert url.startswith(PUBLIC)
        parts = urlsplit(url)
        out[label] = f"{parts.path}?{parts.query}"
    return out


def _setup(tmp_path, pushes, token=None):
    _seed_cache(tmp_path)
    app = _app(tmp_path, token)
    client = local_client(app)
    pilot = _pass(app, client)
    (push,) = [p for p in pushes if p.get_header("Actions")]
    return app, client, pilot, _links(push)


def _pending(pilot) -> list[dict]:
    return pilot.storage.pending_lines(pilot.account)


def test_approve_link_submits_exactly_that_batch(tmp_path, pushes):
    app, client, pilot, links = _setup(tmp_path, pushes)
    assert set(links) == {"Approve all", "Skip", "Open"}
    assert links["Open"] == "/autopilot?"
    batch = _pending(pilot)[0]["batch_id"]
    assert f"/batches/{batch}/approve" in links["Approve all"]

    resp = client.post(links["Approve all"], headers=POST_HEADERS)
    assert resp.status_code == 200 and resp.json() == {"batch_id": batch, "approved": 2}
    assert set(pilot.engine.broker.positions()) == {"SPY", "QQQ"}
    assert _pending(pilot) == [] and pilot.state().mode == "approve"   # mode untouched

    again = client.post(links["Approve all"], headers=POST_HEADERS)  # single use
    assert again.status_code == 409


def test_a_replayed_link_is_refused_and_changes_nothing(tmp_path, pushes):
    """The link rode through the ntfy topic: a second use is a 409, even when
    the batch is still pending (a replayed Skip must not act twice either)."""
    app, client, pilot, links = _setup(tmp_path, pushes)
    first = client.post(links["Skip"], headers=POST_HEADERS)
    assert first.status_code == 200 and first.json()["rejected"] == 2
    pilot.tick()                                    # a fresh batch is pending
    fresh = _pending(pilot)
    assert client.post(links["Skip"], headers=POST_HEADERS).status_code == 409
    assert _pending(pilot) == fresh


def test_a_live_account_is_never_approved_by_link(tmp_path, pushes, monkeypatch):
    app, client, pilot, links = _setup(tmp_path, pushes)
    lines = _pending(pilot)
    batch = lines[0]["batch_id"]
    # Lines as a live engine would have stored them, so only the guard stops it.
    monkeypatch.setattr(pilot.storage, "pending_lines_in_batch", lambda b, m: lines)
    monkeypatch.setattr(pilot, "approve", lambda ids: pytest.fail("approved a live batch"))
    pilot.account = "live"                         # as a live CLI engine would be
    try:
        assert autopilot_service.act_on_batch(app, batch, "approve") == 0
    finally:
        pilot.account = "dry_run"
    assert len(_pending(pilot)) == 2 and pilot.engine.broker.positions() == {}


def test_skip_link_rejects(tmp_path, pushes):
    _, client, pilot, links = _setup(tmp_path, pushes)
    resp = client.post(links["Skip"], headers=POST_HEADERS)
    assert resp.status_code == 200 and resp.json()["rejected"] == 2
    assert _pending(pilot) == [] and pilot.engine.broker.positions() == {}


@pytest.mark.parametrize("mangle", [
    lambda q: q.replace("sig=", "sig=0"),
    lambda q: q.replace("exp=", "exp=1"),
    lambda q: q.replace("/approve?", "/reject?"),
    lambda q: q.split("&sig=")[0] + "&sig=" + "0" * 64,
])
def test_a_bad_signature_changes_nothing(tmp_path, pushes, mangle):
    _, client, pilot, links = _setup(tmp_path, pushes)
    resp = client.post(mangle(links["Approve all"]), headers=POST_HEADERS)
    assert resp.status_code in (403, 422)
    assert len(_pending(pilot)) == 2 and pilot.engine.broker.positions() == {}


def test_an_expired_link_changes_nothing(tmp_path, pushes):
    _, client, pilot, links = _setup(tmp_path, pushes)
    with patch("tradebot.autopilot.links.time.time", lambda: 4_000_000_000):
        resp = client.post(links["Approve all"], headers=POST_HEADERS)
    assert resp.status_code == 403
    assert len(_pending(pilot)) == 2 and pilot.engine.broker.positions() == {}


def test_the_guard_header_is_still_required(tmp_path, pushes):
    _, client, pilot, links = _setup(tmp_path, pushes)
    assert client.post(links["Approve all"]).status_code == 403
    assert len(_pending(pilot)) == 2


def test_links_work_without_the_cookie_when_a_token_is_set(tmp_path, pushes):
    _, client, pilot, links = _setup(tmp_path, pushes, token="s3cret")
    assert client.get("/api/autopilot").status_code == 401        # the gate is on
    assert client.post("/api/autopilot/batches/1/delete?exp=1&sig=x",
                       headers=POST_HEADERS).status_code == 401  # only the two verbs
    resp = client.post(links["Approve all"], headers=POST_HEADERS)
    assert resp.status_code == 200 and resp.json()["approved"] == 2


def test_an_old_batch_link_finds_nothing_after_the_next_pass(tmp_path, pushes):
    _, client, pilot, links = _setup(tmp_path, pushes)
    old = _pending(pilot)[0]["batch_id"]
    pilot.tick()                                    # replaces (expires) the batch
    fresh = _pending(pilot)
    assert fresh and all(ln["batch_id"] != old for ln in fresh)
    resp = client.post(links["Approve all"], headers=POST_HEADERS)
    assert resp.status_code == 200 and resp.json()["approved"] == 0
    assert _pending(pilot) == fresh and pilot.engine.broker.positions() == {}


def test_a_non_ascii_signature_is_a_403_not_a_500(tmp_path):
    client = local_client(_app(tmp_path))
    resp = client.post("/api/autopilot/batches/1/approve?exp=4000000000&sig=%C3%A9",
                       headers=POST_HEADERS)
    assert resp.status_code == 403
