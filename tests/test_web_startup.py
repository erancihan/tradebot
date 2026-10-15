"""What a service manager's log shows at start, ``tradebot-web --check``, and
that stopping the server (uvicorn's answer to SIGTERM) stops the autopilot."""

from __future__ import annotations

import logging

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from tests.web_client import local_client  # noqa: E402

from tradebot.data.cache import BarCache  # noqa: E402
from tradebot.data.synthetic import synthetic_ohlcv  # noqa: E402
from tradebot.storage import Storage  # noqa: E402
from tradebot.web import server  # noqa: E402
from tradebot.web.app import create_app  # noqa: E402
from tradebot.web.services import autopilot_service  # noqa: E402

# The real loader, saved at collection: the suite's session `_offline_guard`
# swaps in a no-op only after every module is imported.
import tradebot.credentials as _credentials  # noqa: E402

_REAL_LOAD_DOTENV = _credentials._maybe_load_dotenv
assert _REAL_LOAD_DOTENV.__name__ == "_maybe_load_dotenv"

KEY, SECRET, TOKEN = "PKSECRETKEYVALUE", "SECRETSECRETVALUE", "tok-secret-value-123"
CONFIG = "mode: paper\nsymbols: [SPY, QQQ]\nstrategy:\n  name: buy_and_hold\n  params: {}\n"


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    """No stray .env, config.yaml or real keys leak in from the developer's tree."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("tradebot.credentials._maybe_load_dotenv", lambda: None)
    for name in ("ALPACA_API_KEY", "ALPACA_API_SECRET", "TRADEBOT_WEB_TOKEN",
                 "TRADEBOT_ALLOWED_HOSTS", "TRADEBOT_CONFIG", "TRADEBOT_DB"):
        monkeypatch.delenv(name, raising=False)


def _config(tmp_path, text=CONFIG) -> str:
    path = tmp_path / "config.yaml"
    path.write_text(text)
    return str(path)


def _app(tmp_path, **kwargs):
    return create_app(trading_db=str(tmp_path / "t.db"), arena_db=str(tmp_path / "a.db"),
                      cache_dir=str(tmp_path / "cache"), **kwargs)


def test_startup_logs_one_line_naming_what_the_server_runs_with(tmp_path, caplog,
                                                                monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", KEY)
    monkeypatch.setenv("ALPACA_API_SECRET", SECRET)
    app = _app(tmp_path, settings_path=_config(tmp_path), access_token=TOKEN,
               allowed_hosts=["localhost", "pi.lan"])
    # With keys present, resume would build a paper broker; the line is the test.
    monkeypatch.setattr(autopilot_service, "resume", lambda app: None)
    with caplog.at_level(logging.INFO, "tradebot.web.app"), local_client(app):
        pass
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("tradebot-web:")]
    assert len(lines) == 1
    line = lines[0]
    for part in (f"config={tmp_path / 'config.yaml'}", f"trading_db={tmp_path / 't.db'}",
                 "allowed_hosts=localhost,pi.lan", "token=set", "alpaca_keys=present",
                 "autopilot_mode=off"):
        assert part in line
    for secret in (KEY, SECRET, TOKEN):
        assert secret not in caplog.text


def test_the_line_reports_absent_keys_no_token_and_the_stored_mode(tmp_path):
    with Storage(tmp_path / "t.db") as st:
        st.set_autopilot_values("dry_run", {"mode": "approve"})
    from tradebot.web.startup import startup_line

    line = startup_line(_app(tmp_path))
    assert "config=defaults" in line and "token=not set" in line
    assert "alpaca_keys=absent" in line and "autopilot_mode=approve" in line


def test_check_prints_the_line_and_exits_0(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("TRADEBOT_WEB_TOKEN", TOKEN)
    code = server.main(["--check", "--config", _config(tmp_path),
                        "--trading-db", str(tmp_path / "t.db"), "--allow-host", "pi.lan"])
    out = capsys.readouterr().out
    assert code == 0
    assert out.startswith("tradebot-web: ") and "pi.lan" in out and "token=set" in out
    assert TOKEN not in out
    assert (tmp_path / "t.db").exists()


@pytest.mark.parametrize("problem", ["missing", "bad strategy"])
def test_check_exits_1_on_a_config_it_could_not_serve(tmp_path, capsys, problem):
    path = (str(tmp_path / "nope.yaml") if problem == "missing"
            else _config(tmp_path, CONFIG.replace("buy_and_hold", "no_such_strategy")))
    code = server.main(["--check", "--config", path, "--trading-db", str(tmp_path / "t.db")])
    assert code == 1
    assert "--check failed" in capsys.readouterr().err


def test_stopping_the_server_stops_a_running_autopilot_loop(tmp_path, monkeypatch):
    monkeypatch.setattr("tradebot.config.AlpacaCredentials.from_env", lambda: None)
    cache = BarCache(tmp_path / "cache")
    for i, sym in enumerate(("SPY", "QQQ")):
        df = synthetic_ohlcv(periods=120, drift=0.001, seed=10 + i)
        cache.store(sym, "1day", df)
        cache.record_coverage(sym, "1day", df.index.min(), df.index.max())
    with Storage(tmp_path / "t.db") as st:
        st.set_autopilot_values("dry_run", {"mode": "auto"})
    app = _app(tmp_path, settings_path=_config(tmp_path))
    with local_client(app):
        pilot = autopilot_service.current(app)
        assert pilot is not None and pilot._thread.is_alive()
    assert not pilot._thread.is_alive()          # the shutdown itself joined it
    assert pilot.running is False


def test_check_reads_the_dotenv_in_the_working_directory(tmp_path, capsys, monkeypatch):
    """The real loader, not the suite's no-op: `.env` comes from the cwd."""
    from tradebot import credentials

    monkeypatch.setattr(credentials, "_maybe_load_dotenv", _REAL_LOAD_DOTENV)
    pytest.importorskip("dotenv")
    work = tmp_path / "work"
    work.mkdir()
    (work / ".env").write_text(f"TRADEBOT_WEB_TOKEN={TOKEN}\n")
    monkeypatch.chdir(work)
    monkeypatch.delenv("TRADEBOT_WEB_TOKEN", raising=False)
    try:
        code = server.main(["--check", "--config", _config(tmp_path),
                            "--trading-db", str(tmp_path / "t.db")])
        out = capsys.readouterr().out
        assert code == 0 and "token=set" in out, out
    finally:
        import os

        os.environ.pop("TRADEBOT_WEB_TOKEN", None)   # the loader set it for real


def test_a_dotenv_above_the_working_directory_is_not_searched(tmp_path, monkeypatch):
    from tradebot import credentials

    pytest.importorskip("dotenv")
    (tmp_path / ".env").write_text("TRADEBOT_WEB_TOKEN=from-a-parent\n")
    work = tmp_path / "child"
    work.mkdir()
    monkeypatch.chdir(work)
    monkeypatch.delenv("TRADEBOT_WEB_TOKEN", raising=False)
    _REAL_LOAD_DOTENV()
    import os

    assert "TRADEBOT_WEB_TOKEN" not in os.environ


def test_only_the_allowlisted_keys_leave_the_dotenv(tmp_path, monkeypatch):
    import os

    from tradebot import credentials

    pytest.importorskip("dotenv")
    monkeypatch.chdir(tmp_path)
    for name in credentials.DOTENV_KEYS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TRADEBOT_DB", "set-wins.db")
    monkeypatch.delenv("TRADEBOT_EVIL", raising=False)
    path_before, pypath_before = os.environ.get("PATH"), os.environ.get("PYTHONPATH")
    (tmp_path / ".env").write_text(
        "PATH=/evil/bin\nPYTHONPATH=/evil/lib\nTRADEBOT_EVIL=1\n"
        "TRADEBOT_DB=from-file.db\nTRADEBOT_CONFIG=/srv/config.yaml\n")
    try:
        _REAL_LOAD_DOTENV()
        assert os.environ.get("PATH") == path_before
        assert os.environ.get("PYTHONPATH") == pypath_before
        assert "TRADEBOT_EVIL" not in os.environ
        assert os.environ["TRADEBOT_DB"] == "set-wins.db"          # set variables win
        assert os.environ["TRADEBOT_CONFIG"] == "/srv/config.yaml"
    finally:
        os.environ.pop("TRADEBOT_CONFIG", None)
