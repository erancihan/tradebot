"""The phone push's Approve all / Skip buttons, end to end.

Links are armed only for the paper account, so the web pilot here is the
paper one, offline: the "paper" label over a simulated broker on cached bars.
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
from tradebot.config import AlpacaCredentials, Settings  # noqa: E402
from tradebot.web.app import create_app  # noqa: E402
from tradebot.web.guard import POST_HEADERS  # noqa: E402
from tradebot.web.services import autopilot_build, autopilot_service  # noqa: E402
from tests.test_web_autopilot import _seed_cache  # noqa: E402
from tests.web_client import local_client  # noqa: E402

PUBLIC = "http://192.168.1.20:8000"


@pytest.fixture(autouse=True)
def _offline_paper(monkeypatch, tmp_path):
    """The web's paper pilot without the network: credentials "present", and
    the paper broker swapped for a simulated one on the cached bars."""
    for key in ("ALPACA_API_KEY", "ALPACA_API_SECRET"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr("tradebot.config.AlpacaCredentials.from_env",
                        lambda: AlpacaCredentials("k", "s"))

    def paper(creds):
        settings = Settings.from_yaml(tmp_path / "config.yaml")
        broker, data, _ = autopilot_build._dry_run(settings, str(tmp_path / "cache"))
        return broker, data, "paper"

    monkeypatch.setattr(autopilot_build, "_paper", paper)


def _dry_run_web(monkeypatch):
    """No credentials: the web pilot is the dry-run one."""
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
        pilot.account = "paper"
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


@pytest.mark.parametrize("path", [
    "/api/autopilot/batches/%D9%A1/approve",     # an Arabic-Indic one: \d matched it
    "/api/autopilot/batches/1/approve/",
    "/api/autopilot/batches/1/approve/x",
    "/api/autopilot/batches/1/reject/",
])
def test_only_ascii_digit_link_paths_skip_the_gate(tmp_path, path):
    client = local_client(_app(tmp_path, token="s3cret"))
    resp = client.post(f"{path}?exp=4000000000&sig={'0' * 64}", headers=POST_HEADERS)
    assert resp.status_code == 401


def test_a_link_looks_up_and_acts_on_its_batch_under_the_autopilot_lock(
        tmp_path, pushes, monkeypatch):
    """The request thread shares the loop's engine and SQLite connection: the
    batch lookup must not run while a pass holds them."""
    app, client, pilot, links = _setup(tmp_path, pushes)
    real, held = pilot.storage.pending_lines_in_batch, []

    def lookup(batch_id, mode):
        held.append(pilot._lock._is_owned())
        return real(batch_id, mode)

    monkeypatch.setattr(pilot.storage, "pending_lines_in_batch", lookup)
    resp = client.post(links["Skip"], headers=POST_HEADERS)
    assert resp.status_code == 200 and resp.json()["rejected"] == 2
    assert held == [True]


def test_a_paper_push_has_approve_and_skip(tmp_path, pushes):
    _, _, pilot, links = _setup(tmp_path, pushes)
    assert pilot.account == "paper"
    assert list(links) == ["Approve all", "Skip", "Open"]


def test_a_dry_run_push_has_only_the_open_button(tmp_path, pushes, monkeypatch):
    """The web cannot act on a simulated account's batch the way the push
    implies, so a dry-run pilot's push carries no Approve or Skip."""
    _dry_run_web(monkeypatch)
    _seed_cache(tmp_path)
    app = _app(tmp_path)
    pilot = _pass(app, local_client(app))
    assert pilot.account == "dry_run" and len(_pending(pilot)) == 2
    (push,) = [p for p in pushes if p.get_header("Actions")]
    assert push.get_header("Actions") == f'view, Open, "{PUBLIC}/autopilot"'


def test_a_foreign_batch_is_a_409_and_changes_nothing(tmp_path, pushes):
    """A batch recorded under another account (here dry_run) is refused out
    loud, never a silent "approved: 0", even with a link signed for paper."""
    _, client, pilot, links = _setup(tmp_path, pushes)
    batch = _pending(pilot)[0]["batch_id"]
    conn = pilot.storage._conn
    conn.execute("UPDATE proposals SET mode = 'dry_run' WHERE batch_id = ?", (batch,))
    conn.execute("UPDATE proposal_batches SET mode = 'dry_run' WHERE id = ?", (batch,))
    conn.commit()
    resp = client.post(links["Approve all"], headers=POST_HEADERS)
    assert resp.status_code == 409
    assert resp.json()["detail"] == "batch belongs to another account"
    assert len(pilot.storage.pending_lines("dry_run")) == 2
    assert pilot.engine.broker.positions() == {}


_SETUP_DETAIL = ("No Alpaca credentials and no cached bars for SPY. "
                 "Pull once with: tradebot data pull SPY")


def _unready(app, monkeypatch):
    """The pilot is gone (e.g. a settings save) and cannot be rebuilt."""
    def fail(*a, **kw):
        raise RuntimeError(_SETUP_DETAIL)

    monkeypatch.setattr(autopilot_build, "build", fail)
    app.state.autopilot = None


def test_an_unready_autopilot_tells_a_link_nothing_about_the_setup(
        tmp_path, pushes, monkeypatch, caplog):
    """Anyone reading the topic holds the link: the 503 is generic, the
    reason (symbols, the pull command) goes to the server log."""
    app, client, pilot, links = _setup(tmp_path, pushes)
    _unready(app, monkeypatch)
    with caplog.at_level("WARNING", logger="tradebot.web.autopilot"):
        resp = client.post(links["Approve all"], headers=POST_HEADERS)
    assert resp.status_code == 503
    assert resp.json() == {"detail": "autopilot not ready"}
    assert "SPY" not in resp.text and "pull" not in resp.text
    assert any(_SETUP_DETAIL in r.getMessage() for r in caplog.records)
