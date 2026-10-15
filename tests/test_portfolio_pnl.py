"""Round trips by average cost from an account's fills (``portfolio_pnl``)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tradebot.models import Fill
from tradebot.portfolio_pnl import (UnmatchedExit, book, fills_from_orders, open_trades,
                                    round_trips, summary, unmatched_exits)

T0 = datetime(2026, 10, 15, 14, 30, tzinfo=timezone.utc)


def _f(symbol: str, qty: float, price: float, day: int, intent: str | None = None) -> Fill:
    return Fill(symbol=symbol, qty=qty, price=price, timestamp=T0 + timedelta(days=day),
                intent=intent)


def test_a_long_round_trip():
    [trade] = round_trips([_f("SPY", 13, 767.24, 0), _f("SPY", -13, 781.02, 5)])
    assert trade.symbol == "SPY" and trade.side == "long" and trade.qty == 13
    assert trade.entry_price == 767.24 and trade.exit_price == 781.02
    assert trade.pnl == pytest.approx((781.02 - 767.24) * 13)
    assert trade.pnl_pct == pytest.approx(781.02 / 767.24 - 1)
    assert trade.entry_ts == T0 and trade.timestamp == T0 + timedelta(days=5)
    assert open_trades([_f("SPY", 13, 767.24, 0), _f("SPY", -13, 781.02, 5)]) == []


def test_scaling_in_at_two_prices_then_one_exit_uses_the_average_cost():
    [trade] = round_trips([_f("QQQ", 10, 100.0, 0), _f("QQQ", 30, 110.0, 1),
                           _f("QQQ", -40, 120.0, 2)])
    assert trade.qty == 40 and trade.entry_price == pytest.approx(107.5)
    assert trade.pnl == pytest.approx((120.0 - 107.5) * 40)


def test_a_partial_exit_realises_part_and_keeps_the_rest_open():
    fills = [_f("SPY", 10, 100.0, 0), _f("SPY", 10, 120.0, 1), _f("SPY", -5, 130.0, 2)]
    closed, still, _ = book(fills)
    assert closed == []
    [held] = still
    assert held.side == "long" and held.qty == 15 and held.avg_price == pytest.approx(110.0)
    assert held.realised == pytest.approx((130.0 - 110.0) * 5)
    assert held.entry_ts == T0


def test_crossing_zero_closes_the_trip_and_opens_a_short_with_the_rest():
    closed, still, _ = book([_f("IWM", 10, 50.0, 0), _f("IWM", -15, 55.0, 1)])
    [trade] = closed
    assert trade.side == "long" and trade.qty == 10 and trade.pnl == pytest.approx(50.0)
    [short] = still
    assert short.side == "short" and short.qty == 5 and short.avg_price == 55.0
    assert short.entry_ts == T0 + timedelta(days=1) and short.realised == 0.0


def test_a_short_round_trip_wins_when_the_price_falls():
    [trade] = round_trips([_f("TSLA", -4, 200.0, 0), _f("TSLA", 4, 180.0, 3)])
    assert trade.side == "short" and trade.pnl == pytest.approx(80.0)
    assert trade.pnl_pct == pytest.approx(0.1)
    [loss] = round_trips([_f("TSLA", -4, 200.0, 0), _f("TSLA", 4, 210.0, 3)])
    assert loss.pnl == pytest.approx(-40.0) and not loss.is_win


def test_symbols_are_booked_apart():
    trades = round_trips([_f("A", 1, 10.0, 0), _f("B", -2, 20.0, 0),
                          _f("A", -1, 12.0, 1), _f("B", 2, 21.0, 2)])
    assert [(t.symbol, t.pnl) for t in trades] == [("A", 2.0), ("B", -2.0)]


def test_the_summary_counts_wins_losses_and_the_profit_factor():
    trades = round_trips([_f("A", 10, 10.0, 0), _f("A", -10, 13.0, 1),      # +30
                          _f("B", 10, 10.0, 0), _f("B", -10, 9.0, 1),       # -10
                          _f("C", 10, 10.0, 0), _f("C", -10, 11.0, 2),      # +10
                          _f("D", 1, 10.0, 0), _f("D", -1, 10.0, 2)])       # break-even
    s = summary(trades)
    assert (s["closed"], s["wins"], s["losses"]) == (4, 2, 1)
    assert s["win_rate"] == pytest.approx(0.5)
    assert s["realised"] == pytest.approx(30.0)
    assert s["avg_win"] == pytest.approx(20.0) and s["avg_loss"] == pytest.approx(-10.0)
    assert s["best"] == pytest.approx(30.0) and s["worst"] == pytest.approx(-10.0)
    assert s["profit_factor"] == pytest.approx(4.0)


def test_without_a_loss_the_profit_factor_is_none():
    s = summary(round_trips([_f("A", 1, 10.0, 0), _f("A", -1, 11.0, 1)]))
    assert s["profit_factor"] is None and s["avg_loss"] is None and s["win_rate"] == 1.0


def test_no_fills_no_trades():
    assert book([]) == ([], [], [])
    s = summary([])
    assert s["closed"] == 0 and s["realised"] == 0 and s["win_rate"] is None
    assert s["best"] is None and s["profit_factor"] is None


def test_order_rows_become_signed_fills_at_the_fill_price():
    rows = [{"symbol": "SPY", "side": "sell", "filled_qty": 5.0, "fill_price": 101.5,
             "filled_at": T0.isoformat(), "ts": "ignored"},
            {"symbol": "SPY", "side": "buy", "filled_qty": 2.0, "fill_price": 99.0,
             "filled_at": None, "ts": T0.isoformat(), "intent": "entry"}]
    fills = fills_from_orders(rows)
    assert [(f.qty, f.price, f.timestamp) for f in fills] == [(-5.0, 101.5, T0),
                                                             (2.0, 99.0, T0)]
    assert all(f.commission == 0.0 for f in fills)
    assert [f.intent for f in fills] == [None, "entry"]      # an old row has none


def test_an_exit_with_no_recorded_buy_is_unmatched_not_a_short():
    """The bot sold a hand-bought holding (the off-list mandate), or a buy
    older than the fill log: no phantom short, no made-up P&L."""
    sell = _f("IWM", -10, 100.0, 0, intent="exit")
    closed, still, unmatched = book([sell])
    assert closed == [] and still == []
    assert unmatched == [UnmatchedExit("IWM", T0, 10.0, 100.0)]
    later = [sell, _f("IWM", 10, 90.0, 1, intent="entry")]
    closed, still, _ = book(later)
    assert closed == []                                   # never a +100 "trade"
    [held] = still
    assert held.side == "long" and held.qty == 10 and held.avg_price == 90.0
    assert summary(round_trips(later))["closed"] == 0
    assert unmatched_exits(later) == [UnmatchedExit("IWM", T0, 10.0, 100.0)]


def test_an_exit_larger_than_the_trip_closes_it_and_leaves_the_rest_unmatched():
    fills = [_f("SPY", 10, 100.0, 0, intent="entry"), _f("SPY", -15, 110.0, 1, intent="exit")]
    closed, still, unmatched = book(fills)
    [trade] = closed
    assert trade.side == "long" and trade.qty == 10 and trade.pnl == pytest.approx(100.0)
    assert still == []                                    # not a 5-share short
    assert unmatched == [UnmatchedExit("SPY", T0 + timedelta(days=1), 5.0, 110.0)]


def test_an_exit_the_same_way_as_the_trip_is_unmatched():
    fills = [_f("SPY", 10, 100.0, 0, intent="entry"), _f("SPY", 4, 101.0, 1, intent="exit")]
    _, still, unmatched = book(fills)
    assert still[0].qty == 10 and [u.qty for u in unmatched] == [4.0]


def test_a_sell_without_an_intent_still_opens_a_short():
    """An old row (no intent recorded): strategies can short, so it opens."""
    _, still, unmatched = book([_f("TSLA", -4, 200.0, 0)])
    assert still[0].side == "short" and unmatched == []
