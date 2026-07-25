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


def _calendar_frame(start, end):
    """Bars the way a real venue stamps them: weekdays only, at the 05:00 UTC open."""
    days = pd.date_range(start, end, freq="B", tz="UTC") + pd.Timedelta(hours=5)
    return pd.DataFrame(
        {"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 100.0},
        index=days,
    )


def test_pulled_window_covers_requests_no_bar_lands_on(tmp_path):
    """A real calendar never lands on the requested boundaries — pull once anyway.

    Regression: coverage used to be inferred from observed bar timestamps, so a
    request starting at midnight (first bar 05:00) or ending on a weekend (last
    bar the Friday before) re-fetched forever and could not replay offline.
    """
    cache = BarCache(tmp_path)
    calls = []

    def fetch(symbol, timeframe, start, end):
        calls.append(symbol)
        return _calendar_frame("2021-12-01", "2023-01-31")

    # 2023-01-31 is a Tuesday but the request is for midnight, before the open;
    # the start likewise precedes that day's 05:00 bar.
    rng = {"start": "2021-12-01", "end": "2023-01-31"}
    first = cache.get("SPY", "1day", fetcher=fetch, **rng)
    assert len(first) > 250 and calls == ["SPY"]

    assert len(cache.get("SPY", "1day", fetcher=fetch, **rng)) == len(first)
    assert calls == ["SPY"]                       # served from disk, no re-fetch

    # ...and it replays with no fetcher at all, which is the offline-first point.
    assert len(cache.get("SPY", "1day", **rng)) == len(first)
    # A narrower request inside the pulled window is covered too.
    assert len(cache.get("SPY", "1day", start="2022-03-01", end="2022-06-30")) > 0


def test_weekend_end_date_is_covered(tmp_path):
    """`real_full_cycle` ends 2024-06-30, a Sunday — no bar exists on it."""
    cache = BarCache(tmp_path)
    calls = []

    def fetch(symbol, timeframe, start, end):
        calls.append(symbol)
        return _calendar_frame("2021-12-01", "2024-06-28")

    cache.get("IWM", "1day", start="2021-12-01", end="2024-06-30", fetcher=fetch)
    assert calls == ["IWM"]
    cache.get("IWM", "1day", start="2021-12-01", end="2024-06-30")
    assert calls == ["IWM"]


def test_disjoint_pulls_stay_separate_until_the_gap_is_filled(tmp_path):
    """A window we never downloaded must not be claimed by spanning neighbours."""
    cache = BarCache(tmp_path)
    cache.store("X", "1day", pd.concat([_calendar_frame("2023-01-01", "2023-01-31"),
                                        _calendar_frame("2023-03-01", "2023-03-31")]))
    cache.record_coverage("X", "1day", "2023-01-01", "2023-01-31")
    cache.record_coverage("X", "1day", "2023-03-01", "2023-03-31")

    assert len(cache.coverage("X", "1day")) == 2
    assert len(cache.get("X", "1day", start="2023-01-05", end="2023-01-20")) > 0
    with pytest.raises(RuntimeError):                      # spans the February hole
        cache.get("X", "1day", start="2023-01-05", end="2023-03-20")

    cache.record_coverage("X", "1day", "2023-01-15", "2023-03-15")   # bridges it
    assert len(cache.coverage("X", "1day")) == 1
    assert len(cache.get("X", "1day", start="2023-01-05", end="2023-03-20")) > 0


def test_unreadable_manifest_degrades_to_fetching(tmp_path):
    cache = BarCache(tmp_path)
    cache.store("Q", "1day", _calendar_frame("2023-01-01", "2023-01-31"))
    cache.coverage_path("Q", "1day").write_text("{ not json")

    assert cache.coverage("Q", "1day") == []
    with pytest.raises(RuntimeError):
        cache.get("Q", "1day", start="2022-01-01", end="2023-12-31")


def test_roundtrip_preserves_ohlcv(tmp_path):
    cache = BarCache(tmp_path)
    df = synthetic_ohlcv(periods=50, seed=9)
    cache.store("Z", "1day", df)
    loaded = cache.load("Z", "1day")
    # The cache names the index 'timestamp' for CSV roundtrip; values must match.
    pd.testing.assert_frame_equal(loaded, df, check_freq=False, check_names=False)
