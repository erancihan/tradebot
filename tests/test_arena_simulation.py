import numpy as np
import pandas as pd

from tradebot.arena import Action, Algo
from tradebot.arena.adapters import EventPolicy, VectorizedPolicy
from tradebot.arena.simulation import SimConfig, simulate
from tradebot.backtest import Backtester
from tradebot.data.synthetic import synthetic_ohlcv
from tradebot.risk import RiskConfig, RiskManager
from tradebot.strategies import Strategy
from tradebot.strategies.sma_crossover import SmaCrossover


def test_simulate_matches_backtester_for_vectorized_strategy():
    """The stepped sim core must agree with the vectorised Backtester."""
    df = synthetic_ohlcv(periods=300, seed=5)
    cfg = RiskConfig(max_position_pct=0.95)

    bt = Backtester(SmaCrossover(10, 30), RiskManager(cfg),
                    initial_cash=10_000, commission=0.0, slippage_bps=1.0)
    expected = bt.run(df, symbol="X")

    policy = VectorizedPolicy(lambda: SmaCrossover(10, 30))
    got = simulate(policy, {"X": df}, RiskManager(cfg), SimConfig(10_000, 0.0, 1.0))

    pd.testing.assert_series_equal(
        expected.equity_curve, got.equity_curve, check_names=False
    )
    assert expected.num_trades == got.num_trades


class _AlwaysLongStrategy(Strategy):
    def target_positions(self, bars):
        return pd.Series(1, index=bars.index, dtype="int64")


class _AlwaysLongAlgo(Algo):
    def on_bar(self, bar, ctx):
        return Action.long()


def test_event_and_vectorized_agree_on_identical_logic():
    df = synthetic_ohlcv(periods=200, seed=2)
    cfg = RiskConfig(max_position_pct=0.95)
    v = simulate(VectorizedPolicy(_AlwaysLongStrategy), {"X": df},
                 RiskManager(cfg), SimConfig(10_000, 0.0, 1.0))
    e = simulate(EventPolicy(_AlwaysLongAlgo), {"X": df},
                 RiskManager(cfg), SimConfig(10_000, 0.0, 1.0))
    assert np.allclose(v.equity_curve.to_numpy(), e.equity_curve.to_numpy())


class _SpyPolicy:
    def __init__(self):
        self.window_lengths = []

    def reset(self):
        self.window_lengths = []

    def decide(self, symbol, window, position, equity):
        self.window_lengths.append(len(window))
        return 0


def test_policy_only_ever_sees_a_growing_past_window():
    df = synthetic_ohlcv(periods=50, seed=1)
    spy = _SpyPolicy()
    simulate(spy, {"X": df}, RiskManager(RiskConfig()), SimConfig())
    # At step i the policy sees exactly i+1 bars — never the future.
    assert spy.window_lengths == list(range(1, 51))


def test_hold_keeps_previous_target():
    """'long' once then 'hold' forever must equal 'always long'."""
    df = synthetic_ohlcv(periods=80, seed=4)

    class _LongThenHold(Algo):
        def __init__(self):
            self.seen = 0

        def on_bar(self, bar, ctx):
            self.seen += 1
            return Action.long() if self.seen == 1 else Action.hold()

    cfg = RiskConfig(max_position_pct=0.95)
    held = simulate(EventPolicy(_LongThenHold), {"X": df},
                    RiskManager(cfg), SimConfig(10_000, 0.0, 0.0))
    always = simulate(EventPolicy(_AlwaysLongAlgo), {"X": df},
                      RiskManager(cfg), SimConfig(10_000, 0.0, 0.0))
    assert np.allclose(held.equity_curve.to_numpy(), always.equity_curve.to_numpy())
