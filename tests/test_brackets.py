"""Bracket exits: stop-loss / take-profit attached to entries.

The whole feature is offline-testable because ``DryRunBroker`` simulates the
resting legs from each bar's high/low. That simulation is deliberately
pessimistic and the tests below pin every branch of it, because the failure mode
of an optimistic fill model is a backtest that looks better than reality.

Note what is *not* asserted anywhere: backtester parity. Brackets are a
live-execution concern and the Backtester does not model them — see the bracket
note in CLAUDE.md's invariants.
"""

from __future__ import annotations

import pandas as pd
import pytest

from tradebot.broker import DryRunBroker
from tradebot.config import Settings
from tradebot.engine import Engine
from tradebot.models import Order, Side, opens_exposure
from tradebot.risk import RiskConfig, RiskManager
from tradebot.strategies import build_strategy


class MovingBars:
    """A data source whose newest bar can be replaced between passes."""

    def __init__(self, bars: list[dict]) -> None:
        self.bars = list(bars)

    def push(self, **bar) -> None:
        self.bars.append(bar)

    def history(self, symbol, timeframe=None, lookback=None):
        idx = pd.date_range("2024-01-01", periods=len(self.bars), freq="1D", tz="UTC")
        return pd.DataFrame(
            [{**b, "volume": 1000.0} for b in self.bars], index=idx
        )[["open", "high", "low", "close", "volume"]]


def _flat(price: float) -> dict:
    return {"open": price, "high": price, "low": price, "close": price}


def _broker(bars: MovingBars) -> DryRunBroker:
    return DryRunBroker(bars, initial_cash=10_000, slippage_bps=0)


def _long_with_stop(bars: MovingBars, stop=95.0, target=None) -> DryRunBroker:
    broker = _broker(bars)
    broker.submit(Order("SPY", 10, Side.BUY, stop_loss=stop, take_profit=target))
    return broker


# --- the exposure predicate ----------------------------------------------------

@pytest.mark.parametrize("current,delta,expected", [
    (0, 10, True),        # open a long
    (10, 5, True),        # add to it
    (10, -4, False),      # trim it
    (10, -10, False),     # close it
    (10, -15, True),      # flip long -> short: a new entry, not a reduction
    (0, -10, True),       # open a short
    (-10, -5, True),      # add to the short
])
def test_only_risk_increasing_fills_count_as_entries(current, delta, expected):
    assert opens_exposure(current, delta) is expected


# --- level computation ---------------------------------------------------------

def test_bracket_levels_mirror_for_a_short():
    risk = RiskManager(RiskConfig(stop_loss_pct=0.05, take_profit_pct=0.10))
    assert risk.bracket_prices(+1, 100.0) == pytest.approx((95.0, 110.0))
    # Short: the stop sits ABOVE the entry and the target below.
    assert risk.bracket_prices(-1, 100.0) == pytest.approx((105.0, 90.0))


def test_no_bracket_config_means_no_levels():
    risk = RiskManager(RiskConfig())
    assert risk.bracket_prices(+1, 100.0) == (None, None)


def test_one_sided_brackets_are_allowed():
    risk = RiskManager(RiskConfig(stop_loss_pct=0.02))
    assert risk.bracket_prices(+1, 100.0) == (98.0, None)


def test_bracket_pct_bounds_are_enforced():
    with pytest.raises(ValueError):
        RiskConfig(stop_loss_pct=0.0)
    with pytest.raises(ValueError):
        RiskConfig(take_profit_pct=1.5)


def test_order_rejects_a_non_positive_bracket_price():
    with pytest.raises(ValueError):
        Order("SPY", 1, Side.BUY, stop_loss=0.0)


# --- trigger simulation --------------------------------------------------------

def test_stop_fires_when_the_bar_trades_through_it():
    bars = MovingBars([_flat(100.0)])
    broker = _long_with_stop(bars)
    bars.push(open=99.0, high=99.0, low=94.0, close=96.0)

    fills = broker.check_brackets()
    assert [f.price for f in fills] == [95.0]
    assert broker.position("SPY").is_flat
    assert broker.portfolio.trades[0].exit_price == 95.0


def test_a_gap_through_the_stop_fills_at_the_open_not_the_stop():
    """A stop is a trigger, not a guaranteed price."""
    bars = MovingBars([_flat(100.0)])
    broker = _long_with_stop(bars)
    bars.push(open=80.0, high=82.0, low=79.0, close=81.0)

    fills = broker.check_brackets()
    assert [f.price for f in fills] == [80.0]      # the open, well below the 95 stop


def test_stop_wins_when_one_bar_touches_both_levels():
    """Intrabar path is unknowable, so assume the worse ordering."""
    bars = MovingBars([_flat(100.0)])
    broker = _long_with_stop(bars, stop=95.0, target=105.0)
    bars.push(open=100.0, high=106.0, low=94.0, close=104.0)

    fills = broker.check_brackets()
    assert [f.price for f in fills] == [95.0]


def test_take_profit_fills_at_its_limit_and_never_better():
    bars = MovingBars([_flat(100.0)])
    broker = _long_with_stop(bars, stop=None, target=105.0)
    bars.push(open=112.0, high=115.0, low=111.0, close=113.0)

    fills = broker.check_brackets()
    assert [f.price for f in fills] == [105.0]     # not the favourable 112 open


def test_an_untouched_bracket_leaves_the_position_alone():
    bars = MovingBars([_flat(100.0)])
    broker = _long_with_stop(bars, stop=95.0, target=105.0)
    bars.push(open=100.0, high=104.0, low=96.0, close=101.0)

    assert broker.check_brackets() == []
    assert broker.position("SPY").qty == 10


def test_short_positions_trigger_on_the_mirrored_side():
    bars = MovingBars([_flat(100.0)])
    broker = _broker(bars)
    broker.submit(Order("SPY", 10, Side.SELL, stop_loss=105.0, take_profit=90.0))
    bars.push(open=101.0, high=106.0, low=100.0, close=105.5)

    fills = broker.check_brackets()
    assert [f.price for f in fills] == [105.0]
    assert broker.position("SPY").is_flat


def test_a_reduction_does_not_rest_a_new_bracket():
    """Trimming a position keeps the original levels; it never installs new ones."""
    bars = MovingBars([_flat(100.0)])
    broker = _long_with_stop(bars, stop=95.0)
    broker.submit(Order("SPY", 4, Side.SELL))           # no bracket on the exit leg
    bars.push(open=99.0, high=99.0, low=94.0, close=96.0)

    fills = broker.check_brackets()
    assert [f.qty for f in fills] == [-6.0]             # closes what is left, at the stop


def test_closing_a_position_cancels_its_bracket():
    bars = MovingBars([_flat(100.0)])
    broker = _long_with_stop(bars, stop=95.0)
    broker.submit(Order("SPY", 10, Side.SELL))
    bars.push(open=99.0, high=99.0, low=90.0, close=91.0)

    assert broker.check_brackets() == []                # nothing rests on a flat book


# --- engine seam ---------------------------------------------------------------

def _engine(bars: MovingBars, broker: DryRunBroker, **risk_kwargs) -> Engine:
    settings = Settings(mode="paper", symbols=["SPY"], strategy_name="buy_and_hold")
    return Engine(
        settings, broker, bars, build_strategy("buy_and_hold", {}),
        RiskManager(RiskConfig(max_position_pct=0.5, **risk_kwargs)),
        storage=None, mode_label="dry_run", enforce_live_ack=False,
    )


def test_engine_attaches_brackets_to_entries_only():
    bars = MovingBars([_flat(100.0)])
    submitted: list[Order] = []
    broker = _broker(bars)
    original = broker.submit
    broker.submit = lambda o: (submitted.append(o), original(o))[1]

    engine = _engine(bars, broker, stop_loss_pct=0.05)
    engine.rebalance()
    assert submitted[0].stop_loss == pytest.approx(95.0)

    # A pass that only trims must not carry a bracket.
    bars.push(**_flat(200.0))                 # price doubles -> the target shrinks
    engine.rebalance()
    assert submitted[-1].side is Side.SELL
    assert submitted[-1].stop_loss is None


def test_a_forward_test_stops_out_and_books_the_loss():
    """End-to-end: the engine's own loop fires the stop before it re-reads equity."""
    bars = MovingBars([_flat(100.0)])
    broker = _broker(bars)
    engine = _engine(bars, broker, stop_loss_pct=0.05)
    engine.rebalance()
    assert broker.position("SPY").qty == 50           # 50% of 10k at 100

    bars.push(open=99.0, high=99.0, low=90.0, close=92.0)
    engine.rebalance()

    trade = broker.portfolio.trades[0]
    assert trade.exit_price == 95.0
    assert trade.pnl == pytest.approx(-250.0)         # 50 shares * 5
    # buy_and_hold still says long, so the engine re-enters on the same pass.
    # That is the honest behaviour of a rebalancing bot: a bracket protects
    # BETWEEN passes, it does not veto a signal that is still live.
    assert not broker.position("SPY").is_flat


def test_alpaca_maps_both_legs_to_a_bracket_and_one_leg_to_an_oto():
    pytest.importorskip("alpaca")
    from alpaca.trading.enums import OrderClass

    from tradebot.broker.alpaca_broker import AlpacaBroker

    both = AlpacaBroker._bracket_kwargs(
        Order("SPY", 1, Side.BUY, stop_loss=95.0, take_profit=110.0))
    assert both["order_class"] is OrderClass.BRACKET
    assert float(both["stop_loss"].stop_price) == 95.0
    assert float(both["take_profit"].limit_price) == 110.0

    one = AlpacaBroker._bracket_kwargs(Order("SPY", 1, Side.BUY, stop_loss=95.0))
    assert one["order_class"] is OrderClass.OTO
    assert "take_profit" not in one

    assert AlpacaBroker._bracket_kwargs(Order("SPY", 1, Side.BUY)) == {}
