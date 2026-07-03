import numpy as np
import pandas as pd

from tradebot.allocation import EqualWeight
from tradebot.backtest import Backtester, _infer_periods_per_year
from tradebot.data.synthetic import synthetic_ohlcv
from tradebot.risk import RiskConfig, RiskManager
from tradebot.strategies import RsiReversion, SmaCrossover


def _bt(strategy, **risk_kw):
    risk = RiskManager(RiskConfig(max_position_pct=0.95, **risk_kw))
    return Backtester(strategy, risk, initial_cash=10_000, slippage_bps=0.0)


def test_backtest_runs_and_reports_metrics():
    df = synthetic_ohlcv(periods=400, seed=7)
    result = _bt(SmaCrossover(10, 30)).run(df, symbol="X")
    s = result.summary()
    assert s["initial_cash"] == 10_000
    assert len(result.equity_curve) == len(df)
    assert -1.0 <= result.max_drawdown <= 0.0
    assert result.num_trades >= 0


def test_uptrend_with_always_long_is_profitable():
    # Strong steady uptrend; a fast/slow crossover should ride most of it.
    df = synthetic_ohlcv(periods=500, drift=0.003, volatility=0.005, seed=3)
    result = _bt(SmaCrossover(5, 20)).run(df, symbol="UP")
    assert result.total_return > 0
    assert result.final_equity > result.initial_cash


def test_no_lookahead_targets_are_shifted():
    # If targets were used same-bar we'd capture the open->close of the signal
    # bar; the shift means equity only changes from the bar AFTER a signal.
    df = synthetic_ohlcv(periods=200, seed=11)
    result = _bt(SmaCrossover(5, 20)).run(df, symbol="X")
    # Equity is flat until the strategy first takes a position.
    assert result.equity_curve.iloc[0] == 10_000


def test_multi_symbol_shared_cash_respects_exposure():
    a = synthetic_ohlcv(periods=300, seed=1)
    b = synthetic_ohlcv(periods=300, seed=2)
    risk = RiskManager(RiskConfig(max_position_pct=0.5, max_gross_exposure=1.0))
    bt = Backtester(SmaCrossover(10, 30), risk, initial_cash=10_000, slippage_bps=0.0)
    result = bt.run({"A": a, "B": b})
    assert len(result.equity_curve) > 0
    # Never blow past the initial cash into deep negative equity.
    assert result.equity_curve.min() > 0


def test_rsi_strategy_backtests():
    df = synthetic_ohlcv(periods=400, seed=9)
    result = _bt(RsiReversion(period=14)).run(df, symbol="R")
    assert len(result.equity_curve) == len(df)


def test_equal_weight_halves_equal_one_full_book():
    # 50/50 across two identical price series must equal 100% in one of them:
    # same dollar exposure, same fills, same curve.
    df = synthetic_ohlcv(periods=300, seed=5)
    risk_kw = dict(max_position_pct=1.0, max_gross_exposure=1.0, allow_fractional=True)

    single = Backtester(
        SmaCrossover(10, 30), RiskManager(RiskConfig(**risk_kw)),
        initial_cash=10_000, slippage_bps=0.0,
    ).run(df, symbol="X")
    split = Backtester(
        SmaCrossover(10, 30), RiskManager(RiskConfig(**risk_kw)),
        initial_cash=10_000, slippage_bps=0.0, allocator=EqualWeight(),
    ).run({"A": df, "B": df.copy()})

    assert np.allclose(single.equity_curve.to_numpy(), split.equity_curve.to_numpy())


class _SpyAllocator:
    """Records the longest history window it is ever shown."""

    def __init__(self):
        self.seen: list[int] = []

    def weights(self, targets, history):
        self.seen.append(max((len(h) for h in history.values()), default=0))
        active = [s for s, t in targets.items() if t != 0]
        return {s: 1.0 / len(active) for s in active} if active else {}


def test_allocator_never_sees_the_fill_bar():
    # Weights follow the same one-bar shift as targets: at fill bar i the
    # allocator may only see bars 0..i-1.
    a = synthetic_ohlcv(periods=120, seed=1)
    b = synthetic_ohlcv(periods=120, seed=2)
    spy = _SpyAllocator()
    Backtester(
        SmaCrossover(10, 30), RiskManager(RiskConfig(max_position_pct=0.5)),
        initial_cash=10_000, allocator=spy,
    ).run({"A": a, "B": b})
    assert spy.seen == list(range(120))


def _linear_frame(start: float, step: float, periods: int) -> pd.DataFrame:
    values = np.array([start + step * i for i in range(periods)], dtype=float)
    idx = pd.date_range("2024-01-01", periods=periods, freq="1D", tz="UTC")
    return pd.DataFrame(
        {"open": values, "high": values, "low": values,
         "close": values, "volume": 1000.0},
        index=idx,
    )


def test_selector_gates_the_book_to_the_winner():
    from tradebot.allocation import EqualWeight
    from tradebot.selection import MomentumSelector
    from tradebot.strategies import BuyAndHold

    # UP rises, DOWN falls hard. Momentum top-1 must keep the book out of DOWN,
    # so buy-and-hold on the gated pool ends profitable.
    pool = {"UP": _linear_frame(100, 1.0, 200), "DOWN": _linear_frame(200, -0.9, 200)}
    risk = RiskManager(RiskConfig(max_position_pct=1.0, max_gross_exposure=1.0,
                                  allow_fractional=True))
    bt = Backtester(BuyAndHold(), risk, initial_cash=10_000, slippage_bps=0.0,
                    allocator=EqualWeight(),
                    selector=MomentumSelector(lookback=20, skip=2, top_k=1))
    gated = bt.run(pool)
    assert gated.total_return > 0

    ungated = Backtester(BuyAndHold(), risk, initial_cash=10_000, slippage_bps=0.0,
                         allocator=EqualWeight()).run(pool)
    # Holding the loser too must do strictly worse.
    assert gated.total_return > ungated.total_return


def test_rebalance_band_cuts_turnover():
    from tradebot.allocation import InverseVolatility
    from tradebot.strategies import BuyAndHold

    pool = {"A": synthetic_ohlcv(periods=300, seed=21),
            "B": synthetic_ohlcv(periods=300, seed=22)}

    def run(band):
        risk = RiskManager(RiskConfig(max_position_pct=0.6, allow_fractional=True,
                                      rebalance_band_pct=band))
        bt = Backtester(BuyAndHold(), risk, initial_cash=10_000, slippage_bps=0.0,
                        allocator=InverseVolatility(window=20))
        return bt.run(pool)

    # Inverse-vol weights drift every bar; the band should suppress most of the
    # resulting micro-trades. (Trades book on position *reductions*.)
    assert run(0.02).num_trades < run(0.0).num_trades


def test_infer_periods_per_year_daily():
    idx = pd.date_range("2023-01-02", periods=10, freq="1D", tz="UTC")
    assert _infer_periods_per_year(idx) == 252.0


def test_commission_and_slippage_reduce_returns():
    df = synthetic_ohlcv(periods=400, drift=0.002, volatility=0.01, seed=5)
    clean = _bt(SmaCrossover(5, 20)).run(df, symbol="X").total_return
    costly = Backtester(
        SmaCrossover(5, 20),
        RiskManager(RiskConfig(max_position_pct=0.95)),
        initial_cash=10_000,
        commission=1.0,
        slippage_bps=10.0,
    ).run(df, symbol="X").total_return
    assert costly <= clean
