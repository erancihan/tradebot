"""Autopilot page: the runner's mode and state on a phone, and the commands."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from tradebot.web.guard import POST_HEADERS  # noqa: E402
from tests.web_client import local_client  # noqa: E402

from tradebot.autopilot import Autopilot  # noqa: E402
from tradebot.data.cache import BarCache  # noqa: E402
from tradebot.data.synthetic import synthetic_ohlcv  # noqa: E402
from tradebot.storage import Storage  # noqa: E402
from tradebot.web.app import create_app  # noqa: E402
from tradebot.web.services import autopilot_service  # noqa: E402


@pytest.fixture(autouse=True)
def _no_credentials(monkeypatch):
    """Offline: the autopilot runs as a dry-run over cached bars."""
    for key in ("ALPACA_API_KEY", "ALPACA_API_SECRET"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr("tradebot.config.AlpacaCredentials.from_env", lambda: None)


def _client(tmp_path) -> TestClient:
    return local_client(create_app(trading_db=str(tmp_path / "t.db"),
                                 arena_db=str(tmp_path / "a.db"),
                                 cache_dir=str(tmp_path / "cache")))


def test_autopilot_page_shows_mode_and_pending(tmp_path):
    body = _client(tmp_path).get("/autopilot").text
    for key in ("off", "approve", "auto"):
        assert f'data-mode="{key}"' in body
    assert "Approve first" in body and "Automatic" in body
    assert 'data-mode="off" aria-pressed="true"' in body     # never touched = off
    assert "dry_run" in body and "stopped" in body
    assert "data-no-pending" in body


def test_autopilot_api_returns_the_state(tmp_path):
    data = _client(tmp_path).get("/api/autopilot").json()
    assert data["state"]["mode"] == "off"
    assert data["state"]["running"] is False
    assert data["state"]["account"] == "dry_run"
    assert [m["key"] for m in data["modes"]] == ["off", "approve", "auto"]
    assert data["pending"] == []


def test_mode_switch_through_the_api(tmp_path):
    _seed_cache(tmp_path)
    client = local_client(_app(tmp_path))
    with patch.object(Autopilot, "start", lambda self: False):   # no thread here
        data = client.post("/api/autopilot", headers=POST_HEADERS, json={"mode": "approve"}).json()
    assert data["state"]["mode"] == "approve"
    assert data["state"]["started_at"] is not None
    with Storage(tmp_path / "t.db") as st:                  # it is durable
        assert st.autopilot_values("dry_run")["mode"] == "approve"
    assert 'data-mode="approve" aria-pressed="true"' in client.get("/partials/autopilot").text


@pytest.mark.parametrize("body", [{"mode": "live"}, {}, {"mode": "auto", "approve": [1]}])
def test_bad_commands_are_refused(tmp_path, body):
    """No mode reaches a live account, and a command means exactly one thing."""
    resp = _client(tmp_path).post("/api/autopilot", headers=POST_HEADERS, json=body)
    assert resp.status_code in (400, 422)


# --- commands that need the engine (dry-run over cached bars) --------------------

def _seed_cache(tmp_path, symbols=("SPY", "QQQ"), periods=120):
    cache = BarCache(tmp_path / "cache")
    for i, sym in enumerate(symbols):
        df = synthetic_ohlcv(periods=periods, drift=0.001, seed=10 + i)
        cache.store(sym, "1day", df)
        cache.record_coverage(sym, "1day", df.index.min(), df.index.max())


def _app(tmp_path, strategy="buy_and_hold"):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("mode: paper\nsymbols: [SPY, QQQ]\n"
                   f"strategy:\n  name: {strategy}\n  params: {{}}\n")
    return create_app(trading_db=str(tmp_path / "t.db"), arena_db=str(tmp_path / "a.db"),
                      cache_dir=str(tmp_path / "cache"), settings_path=str(cfg))


@pytest.mark.parametrize("token, lasting", [("s3cret", True), (None, False)])
def test_the_web_pilots_links_persist_exactly_with_the_token(tmp_path, token, lasting):
    """The link key derives from the access token, so only then does a stored
    push survive a restart (no re-push of the same batch)."""
    _seed_cache(tmp_path)
    cfg = tmp_path / "config.yaml"
    cfg.write_text("mode: paper\nsymbols: [SPY, QQQ]\n")
    app = create_app(trading_db=str(tmp_path / "t.db"), arena_db=str(tmp_path / "a.db"),
                     cache_dir=str(tmp_path / "cache"), settings_path=str(cfg),
                     access_token=token)
    assert autopilot_service.get(app).links_persist is lasting


def _pending_pass(tmp_path):
    """Approve mode plus one pass, run in the test thread with the market open."""
    _seed_cache(tmp_path)
    app = _app(tmp_path)
    client = local_client(app)
    with patch.object(Autopilot, "start", lambda self: False):   # no thread here
        assert client.post("/api/autopilot", headers=POST_HEADERS, json={"mode": "approve"}).status_code == 200
    pilot = autopilot_service.get(app)
    pilot.is_open = lambda now: True
    pilot.tick()
    return client, pilot


def test_approve_through_the_api(tmp_path):
    client, pilot = _pending_pass(tmp_path)
    pending = client.get("/api/autopilot").json()["pending"]
    assert {ln["symbol"] for ln in pending} == {"SPY", "QQQ"}
    page = client.get("/autopilot").text
    assert f'data-reject="{pending[0]["id"]}"' in page and "Approve all" in page

    data = client.post("/api/autopilot", headers=POST_HEADERS, json={"approve": [pending[0]["id"]]}).json()
    assert data["notice"] is None
    assert [ln["id"] for ln in data["pending"]] == [pending[1]["id"]]
    assert set(pilot.engine.broker.positions()) == {pending[0]["symbol"]}


def test_each_pending_line_shows_qty_price_and_reason(tmp_path):
    # On a phone the line is all there is to approve on: the share price sits
    # under the size, so neither has to wrap beside the symbol and badge.
    client, _ = _pending_pass(tmp_path)
    pending = client.get("/api/autopilot").json()["pending"]
    page = client.get("/partials/autopilot").text
    for line in pending:
        item = page.split(f'data-pending-line="{line["id"]}"')[1].split("</li>")[0]
        assert f'{abs(line["order_qty"]):g} sh · $' in item
        assert f'@ ${line["price"]:,.2f} a share' in item
        assert line["reason"] in item and "truncate" not in item


def test_reject_through_the_api(tmp_path):
    client, pilot = _pending_pass(tmp_path)
    ids = [ln["id"] for ln in client.get("/api/autopilot").json()["pending"]]
    data = client.post("/api/autopilot", headers=POST_HEADERS, json={"reject": ids}).json()
    assert data["pending"] == [] and data["state"]["pending"] == 0
    assert pilot.engine.broker.positions() == {}


def test_an_expired_approval_says_so(tmp_path):
    client, pilot = _pending_pass(tmp_path)
    ids = [ln["id"] for ln in client.get("/api/autopilot").json()["pending"]]
    later = pilot.clock() + timedelta(seconds=pilot.poll_seconds + 1)
    pilot.clock = lambda: later
    data = client.post("/api/autopilot", headers=POST_HEADERS, json={"approve": ids}).json()
    assert "expired" in data["notice"]
    assert pilot.engine.broker.positions() == {}


def _seen(pending, scale=1.0) -> dict[str, float]:
    return {str(ln["id"]): ln["notional"] * scale for ln in pending}


def test_the_page_carries_what_it_showed_with_each_approve(tmp_path):
    client, _ = _pending_pass(tmp_path)
    pending = client.get("/api/autopilot").json()["pending"]
    page = client.get("/partials/autopilot").text
    one = pending[0]
    assert f'data-approve="{one["id"]}" data-seen="{one["id"]}:{one["notional"]}"' in page
    every = ",".join(f'{ln["id"]}:{ln["notional"]}' for ln in pending)
    assert f'data-seen="{every}"' in page


def test_an_approval_of_lines_re_sized_since_the_page_showed_them_is_refused(tmp_path):
    """The page showed smaller sizes than the lines carry now (a refresh grew
    them): nothing is bought, the notice says so, and the lines still wait."""
    client, pilot = _pending_pass(tmp_path)
    pending = client.get("/api/autopilot").json()["pending"]
    ids = [ln["id"] for ln in pending]
    data = client.post("/api/autopilot", headers=POST_HEADERS,
                       json={"approve": ids, "seen": _seen(pending, 0.5)}).json()
    assert "re-sized" in data["notice"] and "approve again" in data["notice"]
    assert pilot.engine.broker.positions() == {} and len(data["pending"]) == 2
    data = client.post("/api/autopilot", headers=POST_HEADERS,
                       json={"approve": ids, "seen": _seen(data["pending"])}).json()
    assert data["notice"] is None and set(pilot.engine.broker.positions()) == {"SPY", "QQQ"}


def test_an_approval_after_the_close_says_the_market_is_closed(tmp_path):
    client, pilot = _pending_pass(tmp_path)
    pending = client.get("/api/autopilot").json()["pending"]
    pilot.is_open = lambda now: False
    data = client.post("/api/autopilot", headers=POST_HEADERS,
                       json={"approve": [ln["id"] for ln in pending],
                             "seen": _seen(pending)}).json()
    assert "market is closed" in data["notice"]
    assert data["pending"] == [] and pilot.engine.broker.positions() == {}


def test_a_failing_broker_is_named_in_the_page_notice(tmp_path, monkeypatch):
    client, pilot = _pending_pass(tmp_path)
    pending = client.get("/api/autopilot").json()["pending"]

    def refuse(order):
        raise RuntimeError("insufficient buying power")

    monkeypatch.setattr(pilot.engine.broker, "submit", refuse)
    data = client.post("/api/autopilot", headers=POST_HEADERS,
                       json={"approve": [ln["id"] for ln in pending],
                             "seen": _seen(pending)}).json()
    assert "Order failed: " in data["notice"] and "insufficient buying power" in data["notice"]
    assert {"SPY", "QQQ"} <= set(data["notice"].replace("(", " ").replace(";", " ").split())
    assert "insufficient buying power" in data["state"]["last_error"]
    assert len(data["pending"]) == 2


def test_switching_on_without_cached_bars_says_how_to_get_them(tmp_path):
    client = local_client(_app(tmp_path))
    data = client.post("/api/autopilot", headers=POST_HEADERS, json={"mode": "auto"}).json()
    assert data["state"]["mode"] == "off"                   # nothing was switched on
    assert "tradebot data pull --symbols SPY QQQ" in data["notice"]


# --- the runner thread inside the web process ------------------------------------

def _join(pilot) -> None:
    pilot._thread.join(5)
    assert not pilot._thread.is_alive()


def test_switching_on_starts_the_runner_once_and_off_stops_it(tmp_path):
    _seed_cache(tmp_path)
    app = _app(tmp_path)
    client = local_client(app)
    assert client.post("/api/autopilot", headers=POST_HEADERS, json={"mode": "auto"}).json()["state"]["running"]
    pilot = autopilot_service.get(app)
    thread = pilot._thread
    client.post("/api/autopilot", headers=POST_HEADERS, json={"mode": "approve"})
    assert pilot._thread is thread                          # still the one loop
    data = client.post("/api/autopilot", headers=POST_HEADERS, json={"mode": "off"}).json()
    assert data["state"]["mode"] == "off"
    _join(pilot)
    assert client.get("/api/autopilot").json()["state"]["running"] is False


def test_the_server_resumes_a_running_autopilot_and_stops_it_on_shutdown(tmp_path):
    _seed_cache(tmp_path)
    with Storage(tmp_path / "t.db") as st:
        st.set_autopilot_values("dry_run", {"mode": "auto"})
    app = _app(tmp_path)
    with local_client(app) as client:                         # runs the lifespan
        assert client.get("/api/autopilot").json()["state"]["running"] is True
        pilot = autopilot_service.current(app)
    _join(pilot)
    assert pilot.running is False


def _one_open_account(monkeypatch) -> None:
    """Every runner built trades one simulated account, market open."""
    from tradebot.web.services import autopilot_build

    shared: list = []
    real_dry, real_build = autopilot_build._dry_run, autopilot_build.build

    def one_account(settings, cache_dir):
        if not shared:
            shared.append(real_dry(settings, cache_dir))
        return shared[0]

    def open_build(*a, **kw):
        pilot = real_build(*a, **kw)
        pilot.is_open = lambda now: True
        return pilot

    monkeypatch.setattr(autopilot_build, "_dry_run", one_account)
    monkeypatch.setattr(autopilot_build, "build", open_build)


def test_a_reset_waits_for_the_pass_in_flight_before_a_new_loop_trades(
        tmp_path, monkeypatch):
    """A Settings save lands while a pass is still running (longer than the
    stop wait): the user switches back on at once. The new runner must not
    trade the account until the old pass is done, or both size the same
    empty book and buy it twice."""
    import threading

    from tradebot import advisor

    _seed_cache(tmp_path)
    _one_open_account(monkeypatch)
    monkeypatch.setattr(autopilot_service, "STOP_WAIT_SECONDS", 0.05)
    entered, release, calls = threading.Event(), threading.Event(), []
    real_propose = advisor.propose

    def slow_first(*a, **kw):                      # positions are already read
        calls.append(1)
        if len(calls) == 1:
            entered.set()
            release.wait(10)
        return real_propose(*a, **kw)

    monkeypatch.setattr(advisor, "propose", slow_first)
    app = _app(tmp_path)
    old = autopilot_service.get(app)
    old.set_mode("auto")
    old.start()                                    # (the page's view would wait on the pass)
    assert entered.wait(5)
    assert autopilot_service.reset(app) is True
    switch = threading.Thread(target=autopilot_service.set_mode, args=(app, "auto"))
    switch.start()
    switch.join(0.5)
    assert switch.is_alive()                       # waiting on the old pass
    release.set()
    switch.join(10)
    assert not old._thread.is_alive()
    new = autopilot_service.current(app)
    for _ in range(200):                           # the new loop's first pass
        if new.state().last_pass_at is not None:
            break
        entered.wait(0.025)
    new.stop()
    with Storage(tmp_path / "t.db") as st:
        symbols = [r["symbol"] for r in st._conn.execute("SELECT symbol FROM orders")]
    assert sorted(symbols) == ["QQQ", "SPY"]        # one pass's buys, not two


def test_an_off_autopilot_is_not_built_at_startup(tmp_path):
    app = _app(tmp_path)                                    # nothing cached: build would fail
    with local_client(app) as client:
        assert client.get("/autopilot").status_code == 200
    assert autopilot_service.current(app) is None


# --- a stored config can never stop the server -----------------------------------

def _app_with_brief(tmp_path, minutes):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("mode: paper\nsymbols: [SPY, QQQ]\n"
                   "strategy:\n  name: buy_and_hold\n  params: {}\n"
                   f"autopilot:\n  brief_minutes_before_open: {minutes}\n")
    return create_app(trading_db=str(tmp_path / "t.db"), arena_db=str(tmp_path / "a.db"),
                      cache_dir=str(tmp_path / "cache"), settings_path=str(cfg))


def test_a_zero_minute_brief_means_no_brief(tmp_path):
    """The Settings form accepts 0; it must read as "off", not crash the build."""
    _seed_cache(tmp_path)
    app = _app_with_brief(tmp_path, 0)
    client = local_client(app)
    with patch.object(Autopilot, "start", lambda self: False):
        resp = client.post("/api/autopilot", headers=POST_HEADERS, json={"mode": "approve"})
    assert resp.status_code == 200
    assert autopilot_service.get(app).brief is None


def test_a_config_the_autopilot_rejects_does_not_stop_the_server(tmp_path):
    """A hand-edited negative brief raises ValueError in the build: the server
    still starts and the command answers with a notice, never a 500."""
    _seed_cache(tmp_path)
    with Storage(tmp_path / "t.db") as st:
        st.set_autopilot_values("dry_run", {"mode": "auto"})
    app = _app_with_brief(tmp_path, -5)
    with local_client(app) as client:                         # runs the lifespan
        assert autopilot_service.current(app) is None
        resp = client.post("/api/autopilot", headers=POST_HEADERS, json={"mode": "auto"})
    assert resp.status_code == 200
    assert "brief_minutes_before_open" in resp.json()["notice"]
