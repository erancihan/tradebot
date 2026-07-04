"""The balance ledger itself: money tests must surface start/final balances."""

from tradebot.backtest import Backtester
from tradebot.data.synthetic import synthetic_ohlcv
from tradebot.risk import RiskConfig, RiskManager
from tradebot.strategies import SmaCrossover

from . import conftest


def test_backtests_are_recorded_with_start_and_final_balance():
    df = synthetic_ohlcv(periods=120, seed=1)
    result = Backtester(SmaCrossover(10, 30),
                        RiskManager(RiskConfig(max_position_pct=0.95)),
                        initial_cash=12_345.0).run(df, symbol="LEDG")

    me = "test_backtests_are_recorded_with_start_and_final_balance"
    node = next(k for k in conftest._LEDGER if me in k)
    entry = conftest._LEDGER[node][-1]
    assert entry["symbols"] == "LEDG"
    assert entry["start"] == 12_345.0
    assert entry["final"] == result.final_equity
    assert entry["trades"] == result.num_trades
