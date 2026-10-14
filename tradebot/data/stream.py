"""Push-based bar delivery (websocket), and a fake that replaces it in tests.

Polling asks "is there a new bar yet?" on a timer; a stream is told. That is the
only difference this module introduces — **bars remain the source of truth** and
the consumer keeps deduplicating them, so a stream is an arrival optimisation,
never a second version of history. The live `Engine` deliberately keeps polling:
its rebalance loop is timer-driven by design and rewriting it around a socket
would buy nothing but a new failure mode.

Both implementations satisfy the same tiny interface::

    run(symbols, on_bar)   # blocks, calling on_bar(symbol, one_bar_frame)
    stop()                 # asks run() to return

``on_bar`` receives a **one-row DataFrame** in canonical ``BAR_COLUMNS`` shape
with a tz-aware index — the same shape every other data source in the project
hands out, so a consumer cannot tell a streamed bar from a polled one.

The Alpaca SDK is imported lazily inside :meth:`AlpacaStream.run`, so importing
this module never requires the ``[live]`` extra.
"""

from __future__ import annotations

import logging
import threading

import pandas as pd

from ..models import BAR_COLUMNS

log = logging.getLogger("tradebot.stream")


def _one_bar_frame(ts, values: dict) -> pd.DataFrame:
    """Canonical one-row OHLCV frame with a tz-aware index."""
    index = pd.DatetimeIndex([pd.Timestamp(ts)])
    if index.tz is None:
        index = index.tz_localize("UTC")
    else:
        index = index.tz_convert("UTC")
    return pd.DataFrame([[values[c] for c in BAR_COLUMNS]],
                        columns=list(BAR_COLUMNS), index=index)


class FakeStream:
    """Replays pre-built frames as if they had arrived over a socket.

    Bars are emitted in timestamp order across symbols, so a consumer sees the
    same interleaving a live multi-symbol subscription would produce. No thread,
    no network: :meth:`run` pushes everything and returns, which keeps tests
    deterministic without sleeps or joins.
    """

    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self._frames = frames
        self._stop = threading.Event()

    def run(self, symbols, on_bar) -> None:
        wanted = set(symbols)
        rows: list[tuple[pd.Timestamp, str, pd.Series]] = []
        for symbol, frame in self._frames.items():
            if symbol not in wanted:
                continue
            for ts, row in frame.iterrows():
                rows.append((pd.Timestamp(ts), symbol, row))
        for ts, symbol, row in sorted(rows, key=lambda r: (r[0], r[1])):
            if self._stop.is_set():
                return
            on_bar(symbol, _one_bar_frame(ts, {c: float(row[c]) for c in BAR_COLUMNS}))

    def stop(self) -> None:
        self._stop.set()


class AlpacaStream:
    """Wraps ``alpaca-py``'s ``StockDataStream`` (lazy import, IEX by default)."""

    def __init__(self, api_key: str, api_secret: str, feed: str = "iex") -> None:
        self._key = api_key
        self._secret = api_secret
        self._feed = feed
        self._client = None

    def run(self, symbols, on_bar) -> None:
        from alpaca.data.enums import DataFeed
        from alpaca.data.live import StockDataStream

        feed = DataFeed(self._feed) if not isinstance(self._feed, DataFeed) else self._feed
        self._client = StockDataStream(self._key, self._secret, feed=feed)

        async def _handler(bar) -> None:
            # The SDK hands back one settled bar per symbol per interval; adapt
            # it to the project's canonical frame and hand it straight on.
            frame = _one_bar_frame(bar.timestamp, {
                "open": float(bar.open), "high": float(bar.high),
                "low": float(bar.low), "close": float(bar.close),
                "volume": float(bar.volume),
            })
            try:
                on_bar(bar.symbol, frame)
            except Exception:
                log.exception("Stream consumer failed on %s; dropping that bar", bar.symbol)

        self._client.subscribe_bars(_handler, *list(symbols))
        self._client.run()

    def stop(self) -> None:
        if self._client is not None:
            self._client.stop()
