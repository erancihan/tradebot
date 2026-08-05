"""Push-based bar delivery, and the season feed that consumes it.

The point of these tests is that a streamed season and a polled season
accumulate the *same bars*: streaming is an arrival optimisation, not a second
version of history. `FakeStream` replaces the socket entirely, so none of this
needs the network or the `[live]` extra.
"""

from __future__ import annotations

import pandas as pd
import pytest

from tradebot.arena.season import (
    Season,
    SeasonConfig,
    SeasonStore,
    StreamSeasonFeed,
    run_season,
)
from tradebot.data.stream import AlpacaStream, FakeStream
from tradebot.data.synthetic import synthetic_ohlcv

ALGOS = "./algos"


def _frames(periods: int = 8) -> dict[str, pd.DataFrame]:
    return {
        "AAA": synthetic_ohlcv(periods=periods, seed=1),
        "BBB": synthetic_ohlcv(periods=periods, seed=2),
    }


# --- the stream itself ---------------------------------------------------------

def test_fake_stream_emits_every_bar_in_timestamp_order():
    frames = _frames(5)
    seen: list[tuple[pd.Timestamp, str]] = []
    FakeStream(frames).run(["AAA", "BBB"], lambda s, f: seen.append((f.index[0], s)))

    assert len(seen) == 10
    assert [ts for ts, _ in seen] == sorted(ts for ts, _ in seen)


def test_a_streamed_bar_is_shaped_like_every_other_bar():
    captured: list[pd.DataFrame] = []
    FakeStream(_frames(2)).run(["AAA"], lambda s, f: captured.append(f))

    frame = captured[0]
    assert list(frame.columns) == ["open", "high", "low", "close", "volume"]
    assert len(frame) == 1
    assert frame.index.tz is not None


def test_the_stream_only_delivers_what_was_subscribed():
    seen: list[str] = []
    FakeStream(_frames(3)).run(["AAA"], lambda s, f: seen.append(s))
    assert set(seen) == {"AAA"}


def test_stopping_a_stream_ends_the_run():
    stream = FakeStream(_frames(6))
    seen: list[str] = []

    def on_bar(symbol, frame):
        seen.append(symbol)
        stream.stop()

    stream.run(["AAA", "BBB"], on_bar)
    assert len(seen) == 1


def test_constructing_the_alpaca_stream_imports_no_sdk():
    """Import isolation: the SDK is only touched inside `run`."""
    stream = AlpacaStream("key", "secret")
    assert stream._client is None


# --- the season feed adapter ---------------------------------------------------

def test_stream_feed_drains_one_bar_per_symbol_per_tick():
    feed = StreamSeasonFeed(FakeStream(_frames(3)), ["AAA", "BBB"])
    feed.start(background=False)          # deterministic: pushes everything, returns

    ticks = []
    while (bar := feed.next()) is not None:
        ticks.append(bar)

    assert len(ticks) == 3
    assert all(set(t) == {"AAA", "BBB"} for t in ticks)
    assert all(len(f) == 1 for t in ticks for f in t.values())


def test_an_idle_stream_feed_yields_nothing():
    feed = StreamSeasonFeed(FakeStream({}), ["AAA"])
    feed.start(background=False)
    assert feed.next() is None


def test_a_streamed_season_accumulates_the_same_bars_as_a_replay(tmp_path):
    """The whole point: same bars in, same history out."""
    frames = _frames(6)
    store = SeasonStore(tmp_path / "season.db")
    config = SeasonConfig(name="streamed", symbols=["AAA", "BBB"],
                          metric="total_return", algo_paths=[ALGOS])
    season = Season.create(store, config)

    feed = StreamSeasonFeed(FakeStream(frames), ["AAA", "BBB"])
    feed.start(background=False)
    ticks = run_season(season, feed, max_ticks=6)

    assert ticks == 6
    accumulated = store.load_frames(season.id)
    assert {s: len(f) for s, f in accumulated.items()} == {"AAA": 6, "BBB": 6}
    for symbol, frame in accumulated.items():
        pd.testing.assert_series_equal(
            frame["close"].reset_index(drop=True),
            frames[symbol]["close"].reset_index(drop=True),
            check_names=False,
        )
    assert store.latest_standings(season.id) is not None
    store.close()


def test_a_background_stream_feed_still_delivers(tmp_path):
    """The live path spawns a daemon thread; the buffer is what makes it safe."""
    feed = StreamSeasonFeed(FakeStream(_frames(4)), ["AAA", "BBB"])
    feed.start(background=True)
    feed._thread.join(timeout=10)
    assert not feed._thread.is_alive()

    drained = 0
    while feed.next() is not None:
        drained += 1
    assert drained == 4
