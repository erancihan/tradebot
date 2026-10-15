"""History's benchmark: equal-weight buy and hold of the active list."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pandas as pd
import pytest

from tradebot.data.cache import BarCache
from tradebot.data.synthetic import synthetic_ohlcv
from tradebot.web.services import benchmark


def _bars(closes: list[float], start: str = "2026-10-01") -> pd.DataFrame:
    """Daily bars stamped at 04:00 UTC, weekdays only, as the cache holds them."""
    index = pd.bdate_range(start, periods=len(closes), tz="UTC") + pd.Timedelta(hours=4)
    return pd.DataFrame({"open": closes, "high": closes, "low": closes,
                         "close": closes, "volume": 1.0}, index=index)


SINCE = datetime(2026, 10, 1, 14, 30, tzinfo=timezone.utc)      # a Thursday
UNTIL = datetime(2026, 10, 9, 18, 0, tzinfo=timezone.utc)


def test_one_up_ten_one_down_ten_is_flat():
    frames = {"UP": _bars([100.0, 105.0, 110.0]), "DOWN": _bars([50.0, 47.5, 45.0])}
    series = benchmark.buy_and_hold(frames, 10_000.0, SINCE, UNTIL)
    assert list(series.index) == [date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 5)]
    assert series.iloc[0] == pytest.approx(10_000.0)
    assert series.iloc[-1] == pytest.approx(10_000.0)          # +10% and -10%, equal weight
    one = benchmark.buy_and_hold({"UP": frames["UP"]}, 10_000.0, SINCE, UNTIL)
    assert one.iloc[-1] == pytest.approx(11_000.0)


def test_a_symbol_without_a_close_at_the_start_is_dropped_and_named(tmp_path):
    cache = BarCache(tmp_path)
    cache.store("SPY", "1day", _bars([100.0, 110.0, 121.0]))
    cache.store("LATE", "1day", _bars([10.0, 20.0], start="2026-10-02"))
    out = benchmark.compare(str(tmp_path), ["SPY", "LATE", "QQQ"], 1_000.0, SINCE, UNTIL)
    assert out["symbols"] == ["SPY"]
    assert out["series"].iloc[-1] == pytest.approx(1_210.0)
    assert "LATE" in out["note"] and "QQQ" in out["note"]
    assert "no cached daily bars for QQQ" in out["note"]
    assert out["source"] == "cache" and out["since"] == "2026-10-01"


def test_no_bars_is_no_benchmark_with_a_reason(tmp_path):
    assert benchmark.buy_and_hold({}, 1_000.0, SINCE, UNTIL) is None
    out = benchmark.compare(str(tmp_path), ["SPY", "QQQ"], 1_000.0, SINCE, UNTIL)
    assert out["series"] is None and out["symbols"] == []
    assert out["note"] == "no cached daily bars for SPY, QQQ"
    assert benchmark.compare(str(tmp_path), [], 1_000.0, SINCE, UNTIL)["note"]


def test_bad_prices_never_count_as_a_close():
    frames = {"BAD": _bars([float("nan"), 0.0, 5.0]), "OK": _bars([10.0, 11.0, 12.0])}
    closes, used, dropped = benchmark.window_closes(frames, SINCE, UNTIL)
    assert used == ["OK"] and dropped == ["BAD"]


def test_the_window_starts_at_the_last_close_before_since_and_until_cuts_the_tail():
    """The list is bought at the price of the newest close before the first
    snapshot (Friday's for a Saturday start), so the first session day of a
    bot has a benchmark before that day's close is cached."""
    frames = {"SPY": _bars([100.0, 101.0, 102.0, 103.0, 104.0])}  # Oct 1, 2, 5, 6, 7
    saturday = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
    monday = datetime(2026, 10, 5, 23, 0, tzinfo=timezone.utc)
    series = benchmark.buy_and_hold(frames, 1_000.0, saturday, monday)
    assert list(series.index) == [date(2026, 10, 2), date(2026, 10, 5)]
    assert series.iloc[-1] == pytest.approx(1_000.0 * 102.0 / 101.0)
    later = benchmark.buy_and_hold(frames, 1_000.0, saturday, UNTIL)
    assert later.iloc[-1] == pytest.approx(1_000.0 * 104.0 / 101.0)


def test_a_first_day_bot_has_a_benchmark_from_the_previous_close():
    """Snapshots start today at 13:35 UTC and the cache stops at yesterday's
    close (a daily fetch never caches a forming bar): the benchmark is the
    previous close, flat, instead of missing."""
    frames = {"SPY": _bars([100.0, 101.0]), "QQQ": _bars([50.0, 52.0])}  # Oct 1, 2
    today = datetime(2026, 10, 5, 13, 35, tzinfo=timezone.utc)
    series = benchmark.buy_and_hold(frames, 1_000.0, today, today)
    assert list(series.index) == [date(2026, 10, 2)]
    assert series.iloc[0] == pytest.approx(1_000.0)


def test_without_an_earlier_close_the_start_is_the_next_session():
    frames = {"SPY": _bars([100.0, 110.0], start="2026-10-05")}        # Oct 5, 6
    series = benchmark.buy_and_hold(frames, 1_000.0, SINCE, UNTIL)     # SINCE is Oct 1
    assert list(series.index) == [date(2026, 10, 5), date(2026, 10, 6)]
    assert series.iloc[-1] == pytest.approx(1_100.0)


def test_the_window_ends_where_every_held_name_has_a_close():
    frames = {"A": _bars([10.0, 11.0, 12.0, 13.0]), "B": _bars([20.0, 21.0])}
    series = benchmark.buy_and_hold(frames, 1_000.0, SINCE, UNTIL)
    assert series.index[-1] == date(2026, 10, 2)               # B's last bar; no carried guess


def test_synthetic_bars_are_a_valid_input():
    frames = {"SYN": synthetic_ohlcv(periods=30, start="2026-09-25")}
    series = benchmark.buy_and_hold(frames, 5_000.0, SINCE, UNTIL)
    assert series.iloc[0] == pytest.approx(5_000.0) and len(series) == 9
