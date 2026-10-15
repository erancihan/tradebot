"""History's benchmark: equal-weight buy and hold of the active list."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pandas as pd
import pytest

from tradebot.data.cache import BarCache
from tradebot.data.synthetic import synthetic_ohlcv
from tradebot.web.services import benchmark, benchmark_card


def _bars(closes: list[float], start: str = "2026-10-01") -> pd.DataFrame:
    """Daily bars stamped at 04:00 UTC, weekdays only, as the cache holds them."""
    index = pd.bdate_range(start, periods=len(closes), tz="UTC") + pd.Timedelta(hours=4)
    return pd.DataFrame({"open": closes, "high": closes, "low": closes,
                         "close": closes, "volume": 1.0}, index=index)


SINCE = datetime(2026, 10, 1, 14, 30, tzinfo=timezone.utc)      # a Thursday
UNTIL = datetime(2026, 10, 9, 18, 0, tzinfo=timezone.utc)


def test_one_up_ten_one_down_ten_is_flat():
    # SINCE (14:30 Oct 1) is before Oct 1's close: the list would be bought at
    # Sep 30's close, which is not cached, so the start falls back to Oct 1.
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
    assert series.index[-1] == date(2026, 10, 2)               # B's last bar ends the window


def test_a_one_name_gap_mid_window_holds_its_last_close():
    a = _bars([10.0, 10.0, 10.0])                              # Oct 1, 2, 5
    b = _bars([20.0, 30.0, 40.0]).drop(_bars([0.0, 0.0, 0.0]).index[1])   # Oct 1, 5
    closes, used, _ = benchmark.window_closes({"A": a, "B": b}, SINCE, UNTIL)
    assert used == ["A", "B"] and closes.loc[date(2026, 10, 2), "B"] == 20.0


# --- the start never looks ahead ---------------------------------------------

def test_a_mid_session_start_buys_at_the_previous_close_whatever_is_cached():
    """The first snapshot is Monday 13:35 UTC, before Monday's close: the list
    is bought at Friday's close, both before and after Monday's close is
    cached, so the benchmark's first day cannot change after the fact."""
    monday = datetime(2026, 10, 5, 13, 35, tzinfo=timezone.utc)
    later = datetime(2026, 10, 6, 23, 0, tzinfo=timezone.utc)
    before = {"SPY": _bars([100.0, 101.0])}                     # Thu Oct 1, Fri Oct 2
    after = {"SPY": _bars([100.0, 101.0, 110.0])}               # + Mon Oct 5
    first = benchmark.buy_and_hold(before, 1_000.0, monday, later)
    second = benchmark.buy_and_hold(after, 1_000.0, monday, later)
    assert first.index[0] == second.index[0] == date(2026, 10, 2)
    assert second.iloc[-1] == pytest.approx(1_000.0 * 110.0 / 101.0)   # Monday's move counts


def test_bars_that_end_before_the_start_are_named_with_their_last_close(tmp_path):
    cache = BarCache(tmp_path)
    cache.store("SPY", "1day", _bars([100.0, 110.0, 121.0], start="2026-09-29"))
    cache.store("OLD", "1day", _bars([10.0, 20.0], start="2026-09-24"))   # Sep 24, 25
    until = datetime(2026, 10, 1, 23, 0, tzinfo=timezone.utc)          # SPY is current
    out = benchmark.compare(str(tmp_path), ["SPY", "OLD"], 1_000.0, SINCE, until)
    assert out["symbols"] == ["SPY"]
    assert out["note"] == "bars for OLD end before the start (last 2026-09-25)"


# --- the alpha compares one window --------------------------------------------

def test_the_alpha_uses_the_snapshot_at_the_benchmarks_last_close(tmp_path):
    """SPY is cached for 10 sessions, QQQ for 3: the benchmark ends at QQQ's
    last close, so the equity it is set against is the snapshot of that day,
    not the newest one, and the note names QQQ."""
    cache = BarCache(tmp_path)
    cache.store("SPY", "1day", _bars([100.0 + i for i in range(10)]))  # Oct 1 .. Oct 14
    cache.store("QQQ", "1day", _bars([50.0, 51.0, 52.0]))              # Oct 1, 2, 5
    days = pd.bdate_range("2026-10-01", periods=10, tz="UTC") + pd.Timedelta(hours=15)
    rows = [{"ts": ts.isoformat(), "equity": 1_000.0 + 10.0 * i, "mode": "paper"}
            for i, ts in enumerate(days)]
    out = benchmark.compare(str(tmp_path), ["SPY", "QQQ"], 1_000.0,
                            datetime.fromisoformat(rows[0]["ts"]),
                            datetime.fromisoformat(rows[-1]["ts"]))
    assert out["until"] == "2026-10-05"
    assert out["note"] == "QQQ bars stop at 2026-10-05"
    cell = benchmark_card.card(out, rows)
    assert cell["equity_pct"] == pytest.approx(0.02)            # Oct 5's snapshot: 1,020
    bench_pct = (102.0 / 100.0 + 52.0 / 50.0) / 2 - 1.0
    assert cell["alpha"] == pytest.approx(0.02 - bench_pct)


def test_a_weekend_snapshot_still_reflects_fridays_close():
    rows = [{"ts": "2026-10-01T14:30:00+00:00", "equity": 100.0},
            {"ts": "2026-10-03T14:30:00+00:00", "equity": 105.0},     # Saturday
            {"ts": "2026-10-05T14:30:00+00:00", "equity": 120.0}]     # Monday, open
    assert benchmark_card.equity_through(rows, date(2026, 10, 2)) == 105.0
    assert benchmark_card.equity_through(rows, date(2026, 9, 30)) == 100.0   # before any


def test_synthetic_bars_are_a_valid_input():
    frames = {"SYN": synthetic_ohlcv(periods=30, start="2026-09-25")}
    series = benchmark.buy_and_hold(frames, 5_000.0, SINCE, UNTIL)
    assert series.iloc[0] == pytest.approx(5_000.0) and len(series) == 9
