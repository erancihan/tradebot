"""Every Alpaca HTTP call is bounded: a dead socket cannot freeze a pass.

Offline: a fake transport adapter records the timeout each send carries; no
socket is opened (conftest fails any non-loopback connect anyway).
"""

from __future__ import annotations

import pytest

requests = pytest.importorskip("requests")

from tradebot.alpaca_http import HTTP_TIMEOUT, bound_client, bounded_session  # noqa: E402


class _Recording(requests.adapters.BaseAdapter):
    def __init__(self) -> None:
        self.timeouts: list = []

    def send(self, request, **kwargs):
        self.timeouts.append(kwargs.get("timeout"))
        response = requests.Response()
        response.status_code = 200
        response._content = b"{}"
        response.url = request.url
        return response

    def close(self) -> None:
        pass


def _mounted(session):
    adapter = _Recording()
    session.mount("https://", adapter)
    return adapter


def test_a_bounded_session_sends_every_request_with_the_timeout():
    session = bounded_session()
    adapter = _mounted(session)
    session.get("https://paper-api.alpaca.markets/v2/clock")
    session.request("POST", "https://paper-api.alpaca.markets/v2/orders", json={})
    assert adapter.timeouts == [HTTP_TIMEOUT, HTTP_TIMEOUT]


def test_a_caller_s_own_timeout_wins():
    session = bounded_session()
    adapter = _mounted(session)
    session.get("https://paper-api.alpaca.markets/v2/clock", timeout=3)
    assert adapter.timeouts == [3]


def test_a_timeout_is_an_os_error_so_the_read_retry_covers_it():
    assert issubclass(requests.exceptions.Timeout, OSError)
    assert issubclass(requests.exceptions.ConnectionError, OSError)


def test_the_sdk_clients_are_built_on_a_bounded_session():
    pytest.importorskip("alpaca")
    from tradebot.broker.alpaca_broker import AlpacaBroker
    from tradebot.data.alpaca_data import AlpacaData

    broker = AlpacaBroker("key", "secret", paper=True)
    data = AlpacaData("key", "secret")
    for client in (broker._client, data._client):
        adapter = _mounted(client._session)
        client._session.get("https://paper-api.alpaca.markets/v2/clock")
        assert adapter.timeouts == [HTTP_TIMEOUT]


def test_bound_client_refuses_a_client_without_a_session():
    with pytest.raises(AttributeError):
        bound_client(object())
