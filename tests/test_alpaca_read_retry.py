"""A broker read retries once on a connection error; a submit never does.

Offline: the Alpaca client is a fake, the retry pause is recorded, not slept.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from tradebot.broker.alpaca_broker import AlpacaBroker
from tradebot.models import Order, Side


class _Flaky:
    """A client whose first ``n`` calls of each method fail like a DNS blip."""

    def __init__(self, failures: int = 1) -> None:
        self.failures = {"get_clock": failures, "submit_order": failures}
        self.calls = {"get_clock": 0, "submit_order": 0}

    def get_clock(self):
        self.calls["get_clock"] += 1
        if self.failures["get_clock"] > 0:
            self.failures["get_clock"] -= 1
            raise ConnectionError("nodename nor servname provided")
        return SimpleNamespace(is_open=True)

    def submit_order(self, req):
        self.calls["submit_order"] += 1
        raise ConnectionError("nodename nor servname provided")


def _broker(client) -> tuple[AlpacaBroker, list[float]]:
    broker = AlpacaBroker.__new__(AlpacaBroker)
    broker.paper = True
    broker._client = client
    paused: list[float] = []
    broker._sleep = paused.append
    return broker, paused


def test_a_clock_read_retries_once_after_a_connection_error():
    client = _Flaky(failures=1)
    broker, paused = _broker(client)
    assert broker.is_market_open() is True
    assert client.calls["get_clock"] == 2
    assert paused == [AlpacaBroker.RETRY_SECONDS]


def test_a_second_connection_error_is_the_passs_error():
    client = _Flaky(failures=2)
    broker, paused = _broker(client)
    with pytest.raises(ConnectionError):
        broker.is_market_open()
    assert client.calls["get_clock"] == 2 and len(paused) == 1


def test_a_submit_is_never_retried():
    pytest.importorskip("alpaca")
    client = _Flaky()
    broker, paused = _broker(client)
    with pytest.raises(ConnectionError):
        broker.submit(Order("SPY", 1, Side.BUY))
    assert client.calls["submit_order"] == 1 and paused == []
