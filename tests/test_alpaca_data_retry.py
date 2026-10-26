"""A bar fetch retries once on a connection error, like a broker read.

Offline: the SDK client is a fake, the retry pause is recorded, not slept.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pandas as pd
import pytest

from tradebot.data.alpaca_data import AlpacaData

pytest.importorskip("alpaca.data.requests")


def _frame() -> pd.DataFrame:
    idx = pd.MultiIndex.from_tuples(
        [("SPY", pd.Timestamp("2025-01-02", tz="UTC"))], names=["symbol", "timestamp"])
    return pd.DataFrame({"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0],
                         "volume": [10]}, index=idx)


class _Flaky:
    """The first ``failures`` bar requests fail like a DNS blip."""

    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    def get_stock_bars(self, req):
        self.calls += 1
        if self.failures > 0:
            self.failures -= 1
            raise ConnectionError("nodename nor servname provided")
        return SimpleNamespace(df=_frame())


def _data(client) -> tuple[AlpacaData, list[float]]:
    data = AlpacaData.__new__(AlpacaData)
    data.feed = "iex"
    data._client = client
    paused: list[float] = []
    data._sleep = paused.append
    return data, paused


def test_a_bar_fetch_retries_once_after_a_connection_error():
    client = _Flaky(failures=1)
    data, paused = _data(client)
    df = data.history("SPY", end=datetime(2025, 1, 3, tzinfo=timezone.utc))
    assert len(df) == 1 and client.calls == 2
    assert paused == [AlpacaData.RETRY_SECONDS]


def test_a_batched_fetch_retries_the_same_way():
    client = _Flaky(failures=1)
    data, paused = _data(client)
    frames = data.history_many(["SPY"], end=datetime(2025, 1, 3, tzinfo=timezone.utc))
    assert list(frames) == ["SPY"] and client.calls == 2 and len(paused) == 1


def test_a_second_connection_error_propagates():
    client = _Flaky(failures=2)
    data, paused = _data(client)
    with pytest.raises(ConnectionError):
        data.history("SPY")
    assert client.calls == 2 and len(paused) == 1


def test_an_api_error_is_not_retried():
    class _Rejecting:
        calls = 0

        def get_stock_bars(self, req):
            self.calls += 1
            raise ValueError("invalid symbol")

    client = _Rejecting()
    data, paused = _data(client)
    with pytest.raises(ValueError):
        data.history("SPY")
    assert client.calls == 1 and paused == []
