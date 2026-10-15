"""The pending push's ntfy buttons: exact Actions text, only with a public URL."""

from __future__ import annotations

import pytest

from tradebot.config import Settings
from tradebot.notify import NtfyNotifier, actions_header
from tradebot.notify_actions import safe_public_url

PUBLIC = "https://bot.example.net"
EVENT = {"type": "pending_trades", "batch_id": 12, "count": 1, "mode": "paper",
         "lines": [{"id": 3, "symbol": "SPY", "action": "buy", "qty": 2}]}


def _signer(batch_id: int, verb: str) -> str:
    return f"exp=99&sig={verb}{batch_id}"


OPTS = "method=POST, headers.X-Requested-With=tradebot, clear=true"
EXPECTED = (
    f'http, Approve all, "{PUBLIC}/api/autopilot/batches/12/approve?exp=99&sig=approve12", '
    f'{OPTS}; '
    f'http, Skip, "{PUBLIC}/api/autopilot/batches/12/reject?exp=99&sig=reject12", {OPTS}; '
    f'view, Open, "{PUBLIC}/autopilot"'
)


def test_the_actions_header_is_exact():
    assert actions_header(EVENT, PUBLIC, _signer) == EXPECTED
    assert actions_header(EVENT, PUBLIC + "/", _signer) == EXPECTED
    EXPECTED.encode("latin-1")                      # a header must be latin-1


OPEN_ONLY = f'view, Open, "{PUBLIC}/autopilot"'


@pytest.mark.parametrize("mode", ["live", "dry_run", "replay", None])
def test_only_a_paper_push_has_approve_and_skip(mode):
    """Links are paper-only: a live link would ride the topic to real money,
    and the web cannot act on a dry-run's or a replay's batch."""
    event = {k: v for k, v in {**EVENT, "mode": mode}.items() if v is not None}
    assert actions_header(event, PUBLIC, _signer) == OPEN_ONLY


@pytest.mark.parametrize("event, signer", [
    (EVENT, None),
    ({**EVENT, "batch_id": None}, _signer),
])
def test_without_a_signer_or_a_batch_only_open(event, signer):
    assert actions_header(event, PUBLIC, signer) == OPEN_ONLY


@pytest.mark.parametrize("event, public", [
    (EVENT, None),
    (EVENT, ""),
    ({"type": "order", "symbol": "SPY"}, PUBLIC),
])
def test_no_buttons_without_a_public_url_or_a_pending_batch(event, public):
    assert actions_header(event, public, _signer) is None


class _Resp:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def sent(monkeypatch):
    got: list = []

    def fake_urlopen(req, timeout=None):
        got.append(req)
        return _Resp()

    monkeypatch.setattr("tradebot.notify.urllib.request.urlopen", fake_urlopen)
    return got


def _headers(req) -> dict:
    return {k.lower(): v for k, v in req.header_items()}


def test_the_ntfy_request_carries_the_actions(sent):
    ok = NtfyNotifier("topic", server="http://127.0.0.1:9", public_url=PUBLIC,
                      link_signer=_signer).deliver(EVENT)
    assert ok is True
    (req,) = sent
    assert _headers(req)["actions"] == EXPECTED
    assert _headers(req)["title"] == "tradebot: pending_trades"
    assert req.data.decode() == "batch_id=12 count=1 mode=paper\nbuy 2 SPY"


def test_without_a_public_url_the_push_is_plain_text(sent):
    NtfyNotifier("topic", server="http://127.0.0.1:9", link_signer=_signer).deliver(EVENT)
    assert all("actions" not in _headers(req) for req in sent) and len(sent) == 1


def test_settings_pass_the_public_url_and_signer_to_ntfy():
    settings = Settings.from_dict({"notify": {"ntfy_topic": "abc",
                                              "public_url": PUBLIC + "/"}})
    assert settings.notify_public_url == PUBLIC
    ntfy = settings.build_notifier(_signer).notifiers[1]
    assert (ntfy.public_url, ntfy.link_signer) == (PUBLIC, _signer)
    assert settings.build_notifier().notifiers[1].link_signer is None


UNSAFE = ['https://bot.example.net/a"b', "https://bot.example.net/;x", "https://bot.example.net/,x",
          "https://bot.example.net/\nx", "https://bot.example.net/ x", "https://bot.example.net/?a=1",
          "https://bot.example.net/#f", "https://u:p@bot.example.net", "ftp://bot.example.net",
          "https://böt.example.net", "http://host:99999", "http://", "bot.example.net", 42]


@pytest.mark.parametrize("url", UNSAFE)
def test_an_unsafe_public_url_from_yaml_sends_a_plain_push(sent, caplog, url):
    """A hand-edited config.yaml is never validated by the Settings page: a
    quote, comma or semicolon would add actions, a newline kill every push."""
    settings = Settings.from_dict({"notify": {"ntfy_topic": "abc",
                                              "ntfy_server": "http://127.0.0.1:9",
                                              "public_url": url}})
    with caplog.at_level("WARNING", logger="tradebot.notify"):
        assert settings.build_notifier(_signer).notifiers[1].deliver(EVENT) is True
    (req,) = sent
    assert "actions" not in _headers(req)
    warnings = [r for r in caplog.records if "public_url" in r.getMessage()]
    assert len(warnings) == 1


@pytest.mark.parametrize("url, safe", [
    (PUBLIC, PUBLIC), (PUBLIC + "/", PUBLIC), ("http://192.168.1.20:8000", "http://192.168.1.20:8000"),
    ("https://example.net/trade-bot/x_y~z%20", "https://example.net/trade-bot/x_y~z%20"),
    *((u, None) for u in UNSAFE), (None, None), ("", None),
])
def test_safe_public_url(url, safe):
    assert safe_public_url(url) == safe
