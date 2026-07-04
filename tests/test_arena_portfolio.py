"""Cross-sectional (portfolio) contestants: a whole book competes as one entry."""

from pathlib import Path

import pandas as pd
import pytest

from tradebot.arena.interfaces import PortfolioAlgo
from tradebot.arena.scenario import Scenario
from tradebot.arena.tournament import run_tournament
from tradebot.data.synthetic import synthetic_ohlcv

PORTFOLIO_SRC = """
from tradebot.allocation import EqualWeight
from tradebot.arena import PortfolioAlgo, register
from tradebot.selection import MomentumSelector
from tradebot.strategies import BuyAndHold

@register(name="book", author="t", tags=("portfolio",))
class Book(PortfolioAlgo):
    def __init__(self):
        super().__init__(
            strategy=BuyAndHold(),
            selector=MomentumSelector(lookback=30, skip=3, top_k=2),
            allocator=EqualWeight(),
        )
"""


def _algo_file(tmp_path) -> str:
    p = tmp_path / "book.py"
    p.write_text(PORTFOLIO_SRC)
    return str(p)


def _frames():
    return {s: synthetic_ohlcv(periods=200, seed=i) for i, s in
            enumerate(["A", "B", "C"], start=1)}


def test_register_detects_portfolio_kind(tmp_path):
    from tradebot.arena.loader import discover

    contestants, errors = discover([_algo_file(tmp_path)])
    assert errors == []
    assert len(contestants) == 1
    assert contestants[0].kind == "portfolio"
    spec = contestants[0].make()
    assert spec.selector is not None and spec.allocator is not None


def test_portfolio_algo_requires_strategy_and_allocator():
    from tradebot.allocation import EqualWeight
    from tradebot.strategies import BuyAndHold

    with pytest.raises(ValueError, match="strategy"):
        PortfolioAlgo(strategy=None, allocator=EqualWeight())
    with pytest.raises(ValueError, match="allocator"):
        PortfolioAlgo(strategy=BuyAndHold(), allocator=None)


def test_portfolio_contestant_matches_backtester_stack(tmp_path):
    """The arena must run a portfolio entry exactly like the Backtester would."""
    from tradebot.allocation import EqualWeight
    from tradebot.backtest import Backtester
    from tradebot.risk import RiskConfig, RiskManager
    from tradebot.selection import MomentumSelector
    from tradebot.strategies import BuyAndHold

    frames = _frames()
    scenario = Scenario(name="xs", symbols=list(frames), slippage_bps=1.0,
                        risk=RiskConfig(max_position_pct=0.6, max_gross_exposure=1.0))

    outcome = run_tournament([_algo_file(tmp_path)], scenario, metric="total_return",
                             isolation="thread", frames=frames)
    entry = outcome.leaderboard.entries[0]
    assert entry.ok and entry.kind == "portfolio"

    bt = Backtester(BuyAndHold(),
                    RiskManager(RiskConfig(max_position_pct=0.6, max_gross_exposure=1.0)),
                    initial_cash=scenario.initial_cash, commission=0.0, slippage_bps=1.0,
                    allocator=EqualWeight(),
                    selector=MomentumSelector(lookback=30, skip=3, top_k=2))
    expected = bt.run(frames)

    pd.testing.assert_series_equal(
        expected.equity_curve, entry.result.equity_curve, check_names=False
    )
    assert expected.num_trades == entry.result.num_trades


def test_portfolio_contestant_survives_hard_process_isolation(tmp_path):
    """Fork + sandbox must handle the composed stack (default tournament path)."""
    frames = _frames()
    scenario = Scenario(name="xs", symbols=list(frames))
    outcome = run_tournament([_algo_file(tmp_path)], scenario,
                             metric="sharpe", frames=frames)  # default: process
    entry = outcome.leaderboard.entries[0]
    assert entry.ok and entry.result is not None


def test_portfolio_and_per_symbol_entries_share_one_leaderboard(tmp_path):
    (tmp_path / "mixed.py").write_text(
        PORTFOLIO_SRC
        + "\n"
        "from tradebot.strategies import SmaCrossover\n"
        "@register(name='plain_trend', author='t')\n"
        "class PlainTrend(SmaCrossover):\n"
        "    def __init__(self): super().__init__(fast=10, slow=30)\n"
    )
    scenario = Scenario(name="xs", symbols=["A", "B", "C"])
    outcome = run_tournament([str(tmp_path / "mixed.py")], scenario,
                             metric="total_return", isolation="thread",
                             frames=_frames())
    by = {e.name: e for e in outcome.leaderboard.entries}
    assert by["book"].ok and by["plain_trend"].ok
    assert {by["book"].rank, by["plain_trend"].rank} == {1, 2}


def test_cross_sectional_scenario_rewards_selection():
    """On the shipped spread scenario, ranking the pool beats holding all of it."""
    scenario = Scenario.from_yaml(Path(__file__).resolve().parents[1]
                                  / "scenarios" / "cross_sectional.yaml")
    algos = Path(__file__).resolve().parents[1] / "algos"
    outcome = run_tournament([str(algos)], scenario, metric="total_return",
                             isolation="thread")
    by = {e.name: e for e in outcome.leaderboard.entries}
    assert by["xs_momentum"].ok
    # The momentum book should find the persistent leaders and beat the
    # everything-holder on the same pool.
    assert by["xs_momentum"].total_return > by["buy_and_hold"].total_return
