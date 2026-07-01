import pandas as pd
import pytest

from tradebot.data.cache import BarCache
from tradebot.data.synthetic import synthetic_ohlcv


def _fetcher(calls, periods=300):
    def fetch(symbol, timeframe, start, end):
        calls.append((symbol, timeframe))
        return synthetic_ohlcv(periods=periods, start="2023-01-01", seed=1)
    return fetch


def test_miss_fetches_stores_then_hit_does_not_refetch(tmp_path):
    cache = BarCache(tmp_path)
    calls = []
    fetch = _fetcher(calls)

    first = cache.get("SPY", "1day", fetcher=fetch)
    assert len(first) == 300
    assert cache.path("SPY", "1day").exists()
    assert calls == [("SPY", "1day")]

    # Second call (no range constraint) is fully covered by the cache.
    second = cache.get("SPY", "1day", fetcher=fetch)
    assert len(second) == 300
    assert calls == [("SPY", "1day")]            # no second fetch


def test_get_slices_to_requested_range(tmp_path):
    cache = BarCache(tmp_path)
    df = synthetic_ohlcv(periods=100, start="2023-01-01", freq="1D", seed=2)
    cache.store("X", "1day", df)

    start, end = df.index[10], df.index[20]
    got = cache.get("X", "1day", start=str(start.date()), end=str(end.date()))
    assert len(got) == 11                          # inclusive slice [10..20]
    assert got.index.min() == start and got.index.max() == end


def test_partial_coverage_triggers_fetch_and_merges(tmp_path):
    cache = BarCache(tmp_path)
    # Pre-seed only the first half of the year.
    early = synthetic_ohlcv(periods=180, start="2023-01-01", freq="1D", seed=3)
    cache.store("Y", "1day", early)

    calls = []

    def fetch(symbol, timeframe, start, end):
        calls.append(symbol)
        return synthetic_ohlcv(periods=365, start="2023-01-01", freq="1D", seed=3)

    # Request a date beyond the cached range -> must fetch + merge.
    got = cache.get("Y", "1day", start="2023-01-01", end="2023-12-31", fetcher=fetch)
    assert calls == ["Y"]
    assert len(got) >= 180
    assert got.index.is_monotonic_increasing
    assert not got.index.has_duplicates


def test_miss_without_fetcher_raises(tmp_path):
    cache = BarCache(tmp_path)
    with pytest.raises(RuntimeError):
        cache.get("NOPE", "1day")


def test_roundtrip_preserves_ohlcv(tmp_path):
    cache = BarCache(tmp_path)
    df = synthetic_ohlcv(periods=50, seed=9)
    cache.store("Z", "1day", df)
    loaded = cache.load("Z", "1day")
    # The cache names the index 'timestamp' for CSV roundtrip; values must match.
    pd.testing.assert_frame_equal(loaded, df, check_freq=False, check_names=False)
