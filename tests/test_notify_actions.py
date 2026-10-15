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


def test_a_live_push_has_no_approve_button():
    """The link rides through the topic: never an approve for real money."""
    text = actions_header({**EVENT, "mode": "live"}, PUBLIC, _signer)
    assert text == EXPECTED.split("; ", 1)[1]
    assert "approve" not in text and text.startswith("http, Skip, ")


@pytest.mark.parametrize("event, public, signer", [
    (EVENT, None, _signer),
    (EVENT, "", _signer),
    (EVENT, PUBLIC, None),
    ({**EVENT, "batch_id": None}, PUBLIC, _signer),
    ({"type": "order", "symbol": "SPY"}, PUBLIC, _signer),
])
def test_no_buttons_without_everything_they_need(event, public, signer):
    assert actions_header(event, public, signer) is None


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
    NtfyNotifier("topic", server="http://127.0.0.1:9", public_url=PUBLIC).deliver(EVENT)
    assert all("actions" not in _headers(req) for req in sent) and len(sent) == 2


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
