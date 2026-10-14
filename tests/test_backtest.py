import numpy as np
import pandas as pd
import pytest

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


# --- absolute look-ahead guards ---------------------------------------------
# These are deliberately SINGLE-ENGINE. The backtester-vs-arena lockstep tests
# cannot catch a mistake made identically in both loops — that is exactly how
# the sizing-mark look-ahead survived (see `_sizing_marks`). Every shift in the
# execution path needs one guard that is true in absolute terms, not relative
# to the other engine.

def _spy_on_sizing(df, strategy=None, **risk_kw):
    """Run a backtest, recording the (equity, prices, qty) at every bar."""
    from tradebot.strategies import BuyAndHold

    risk = RiskManager(RiskConfig(allow_fractional=True, max_position_pct=1.0,
                                  max_gross_exposure=1.0, rebalance_band_pct=0.0,
                                  **risk_kw))
    seen = []
    original = risk.allocate

    def spy(targets, equity, prices, weights=None):
        out = original(targets, equity, prices, weights)
        seen.append((equity, dict(prices), dict(out)))
        return out

    risk.allocate = spy
    Backtester(strategy or BuyAndHold(), risk, initial_cash=10_000,
               slippage_bps=0.0).run(df, symbol="X")
    return seen


def test_sizing_never_sees_the_fill_bars_close():
    """Perturbing a bar's CLOSE must not change the fill sized at its OPEN.

    Regression for the sizing look-ahead: the loop used to mark the book at the
    fill bar's close, so every position size depended on the intra-bar return
    of the bar it was being filled on.
    """
    i = 60
    base = synthetic_ohlcv(periods=200, seed=3)
    pert = base.copy()
    pert.iloc[i, pert.columns.get_loc("close")] = base.iloc[i]["close"] * 0.85
    pert.iloc[i, pert.columns.get_loc("low")] = min(
        base.iloc[i]["low"], base.iloc[i]["close"] * 0.85)

    a, b = _spy_on_sizing(base), _spy_on_sizing(pert)

    assert base.iloc[i]["open"] == pert.iloc[i]["open"]      # fill price untouched
    assert [x[2] for x in a[:i]] == [x[2] for x in b[:i]]    # history untouched
    assert a[i][0] == b[i][0], "sizing equity at the fill bar saw that bar's close"
    assert a[i][2] == b[i][2], "quantity filled at the open moved with a future close"


def test_selector_verdict_cannot_be_acted_on_the_bar_it_is_formed():
    """A membership verdict formed on bar t's close is only tradable at t+1.

    The fixture makes same-bar action unmistakably profitable. JUMP is the worst
    momentum pick until, on one bar, it opens at 100 and closes at 130 — so the
    verdict that first selects it is formed by a move that is still *inside* the
    bar a same-bar engine would fill at. Acting on the shifted verdict buys the
    next open at 130 and captures nothing; acting same-bar buys at 100 and books
    the whole 30%.

    The jump must straddle the open, not precede it: a fixture where the jump
    bar already opens at 130 passes with the shift deleted and guards nothing.
    """
    from tradebot.selection import MomentumSelector
    from tradebot.strategies import BuyAndHold

    n, jump = 60, 40
    # STEADY drifts gently up so it strictly wins momentum before the jump —
    # otherwise the tie is broken arbitrarily and the book may already hold JUMP.
    steady = np.linspace(100.0, 105.0, n)
    jump_close = np.full(n, 100.0)
    jump_close[jump:] = 130.0
    jump_open = np.full(n, 100.0)
    jump_open[jump + 1:] = 130.0          # the jump happens between open and close

    idx = pd.date_range("2024-01-01", periods=n, freq="1D", tz="UTC")

    def frame(opens, closes):
        return pd.DataFrame(
            {"open": opens, "high": np.maximum(opens, closes),
             "low": np.minimum(opens, closes), "close": closes, "volume": 1000.0},
            index=idx)

    result = Backtester(
        BuyAndHold(),
        RiskManager(RiskConfig(allow_fractional=True, max_position_pct=1.0,
                               max_gross_exposure=1.0)),
        initial_cash=10_000, slippage_bps=0.0,
        # exit_rank is explicit: the default (top_k + max(top_k//2, 1)) equals
        # the pool size here, which freezes membership at the first verdict and
        # would make this test vacuous.
        selector=MomentumSelector(lookback=10, skip=0, top_k=1, exit_rank=1),
    ).run({"JUMP": frame(jump_open, jump_close),
           "STEADY": frame(steady, steady)})

    # The book may earn STEADY's gentle drift; it must never book the 30% jump.
    assert result.equity_curve.pct_change().max() < 0.10
    assert result.total_return < 0.10


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
