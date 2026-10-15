"""Discover: rank an unwatched pool by the MomentumSelector score, offline."""

from __future__ import annotations

import math
from datetime import date

import pandas as pd
import pytest

from tradebot.data.synthetic import synthetic_ohlcv
from tradebot.selection.ranked import MomentumSelector
from tradebot.universe.discover import (
    DiscoverResult,
    cached_daily_symbols,
    discover,
    reason_for,
    short_money,
)
from tradebot.universe.screen import LiquidityScreen

NAMES = [f"S{c}" for c in "ABCDEFGHIJKL"]          # twelve names, one index


def _frames(periods=300, names=NAMES) -> dict[str, pd.DataFrame]:
    return {s: synthetic_ohlcv(periods=periods, seed=100 + i, drift=0.0004 * (i - 5))
            for i, s in enumerate(names)}


def _fetch(frames):
    calls: list[list[str]] = []

    def frames_for(symbols):
        calls.append(list(symbols))
        return {s: frames[s] for s in symbols if s in frames}

    return frames_for, calls


def test_ranking_matches_the_momentum_selector_scores():
    frames = _frames()
    frames_for, _ = _fetch(frames)
    result = discover(frames_for, NAMES, top_n=len(NAMES))
    expected = MomentumSelector(lookback=126, skip=21).scores(frames).iloc[-1]
    expected = expected.sort_values(ascending=False)
    assert [r.symbol for r in result.rows] == list(expected.index)
    for row in result.rows:
        assert row.score == pytest.approx(float(expected[row.symbol]), abs=1e-12)
        assert row.price == pytest.approx(float(frames[row.symbol]["close"].iloc[-1]))


def test_top_n_and_exclusions_and_the_pool_fetched():
    frames = _frames()
    frames_for, calls = _fetch(frames)
    full = discover(frames_for, NAMES, top_n=len(NAMES))
    best, second = full.rows[0].symbol, full.rows[1].symbol
    result = discover(frames_for, NAMES, top_n=10, exclude=[best.lower(), second])
    assert len(result.rows) == 10
    assert {best, second}.isdisjoint(r.symbol for r in result.rows)
    assert best not in calls[-1] and second not in calls[-1]   # never even fetched
    assert result.provenance["excluded"] == sorted([best, second])


def test_warmup_short_and_illiquid_symbols_are_dropped():
    frames = _frames(names=["LONG", "THIN"])
    frames["SHORT"] = synthetic_ohlcv(periods=100, seed=7)        # < 127 bars
    frames["THIN"] = frames["THIN"].assign(volume=1.0)            # ADV ~ $100
    frames["BAD"] = synthetic_ohlcv(periods=300, seed=8).assign(close=math.nan)
    frames_for, _ = _fetch(frames)
    result = discover(frames_for, list(frames))
    assert [r.symbol for r in result.rows] == ["LONG"]
    assert result.provenance["pool"] == 4 and result.provenance["ranked"] == 1


def test_frames_are_cut_at_as_of_and_provenance_says_so():
    frames = _frames(names=["SA"])
    frames_for, _ = _fetch(frames)
    cut = frames["SA"].index[250].date()
    result = discover(frames_for, ["SA"], as_of=cut, source="alpaca")
    upto = frames["SA"].iloc[:251]
    assert result.rows[0].price == pytest.approx(float(upto["close"].iloc[-1]))
    expected = MomentumSelector(lookback=126, skip=21).scores({"SA": upto}).iloc[-1, 0]
    assert result.rows[0].score == pytest.approx(float(expected))
    prov = result.provenance
    assert prov["source"] == "alpaca" and prov["as_of"] == cut.isoformat()
    assert prov["bars"] == 251 and prov["end"].startswith(cut.isoformat())
    assert prov["start"].startswith(str(upto.index[0].date()))


def test_reason_text_is_one_short_sentence():
    assert reason_for(0.34, 42e6) == "Up 34% over 6 months to last month; $42M a day traded."
    assert reason_for(-0.051, 1.25e9) == ("Down 5% over 6 months to last month; "
                                          "$1.2B a day traded.")
    assert short_money(850_000) == "$850K" and short_money(12) == "$12"


def test_an_empty_pool_is_an_empty_result_not_a_fetch():
    frames_for, calls = _fetch({})
    result = discover(frames_for, ["SPY"], exclude=["SPY"])
    assert isinstance(result, DiscoverResult) and result.rows == []
    assert calls == [] and result.provenance["bars"] == 0
    assert result.provenance["as_of"] is None


def test_a_custom_screen_is_honoured():
    frames = _frames()
    frames_for, _ = _fetch(frames)
    strict = LiquidityScreen(min_price=1e9)
    assert discover(frames_for, NAMES, screen=strict).rows == []


def test_cached_daily_symbols_lists_the_daily_cache_only(tmp_path):
    assert cached_daily_symbols(tmp_path / "missing") == []
    for tf, sym in (("1day", "SPY"), ("1day", "QQQ"), ("1hour", "IWM")):
        (tmp_path / tf).mkdir(exist_ok=True)
        (tmp_path / tf / f"{sym}.csv").write_text("timestamp,close\n")
    (tmp_path / "1day" / "SPY.coverage.json").write_text("[]")
    assert cached_daily_symbols(tmp_path) == ["QQQ", "SPY"]


def test_as_of_date_type_is_accepted():
    """A plain ``date`` cuts: every bar after it is dropped, not just labelled."""
    frames = _frames(names=["SA"])
    frames_for, _ = _fetch(frames)
    last = frames["SA"].index[-1]
    assert discover(frames_for, ["SA"], as_of=date(2099, 1, 1)).provenance["bars"] == 300
    cut = (last - pd.Timedelta(days=10)).date()
    result = discover(frames_for, ["SA"], as_of=cut)
    assert pd.Timestamp(result.provenance["end"]).date() == cut
    assert result.provenance["bars"] == 290
    assert result.rows[0].price == pytest.approx(float(frames["SA"]["close"].iloc[-11]))


def test_a_frame_the_cache_stopped_updating_is_dropped_as_stale():
    frames = _frames(names=["FRESH", "EDGE", "OLD"])
    frames["EDGE"] = frames["EDGE"].iloc[:-5]       # five sessions behind: kept
    frames["OLD"] = frames["OLD"].iloc[:-6]         # six behind: stale
    frames_for, _ = _fetch(frames)
    result = discover(frames_for, list(frames), top_n=3)
    assert sorted(r.symbol for r in result.rows) == ["EDGE", "FRESH"]
    assert result.provenance["stale"] == 1 and result.provenance["screened"] == 2
