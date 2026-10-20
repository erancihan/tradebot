"""The strategy sees the same history in a live pass as in the backtest.

``supertrend`` (recursive bands), ``rsi_reversion`` (a held state carried
forward) and every EMA are stateful over the whole frame, so a verdict computed
on a truncated fetch window can differ from the Backtester's full-frame
``target_positions``. The engine and the Today refresh hand the strategy the
full stored history instead (``advisor.history``), as they already did for the
selector.
"""

from __future__ import annotations

import pandas as pd
import pytest

from tradebot.broker import DryRunBroker
from tradebot.config import Settings
from tradebot.data import ReplayData
from tradebot.data.synthetic import synthetic_ohlcv
from tradebot.engine import Engine
from tradebot.risk import RiskConfig, RiskManager
from tradebot.storage import Storage
from tradebot.strategies import STRATEGIES

#: Metas bound ``latest_target`` to a tail by design (the arena's time budget);
#: theirs is checked against the arena's growing-window verdict instead.
TAIL_BOUNDED = {"follow_leader", "ensemble_vote"}
PERIODS, STRIDE = 180, 1


class WindowedReplay(ReplayData):
    """A replay that honours ``lookback`` in calendar days, as Alpaca does."""

    def history(self, symbol, timeframe=None, lookback=None):
        bars = super().history(symbol, timeframe, lookback)
        if lookback is None:
            return bars
        return bars.loc[bars.index[-1] - pd.Timedelta(days=lookback):]


def _engine_verdicts(name: str, df: pd.DataFrame, db: str) -> dict:
    """The strategy target of every ``STRIDE``-th engine pass, by bar time."""
    data = WindowedReplay({"X": df}, warmup=2)
    broker = DryRunBroker(data, initial_cash=10_000, slippage_bps=0)
    settings = Settings(mode="paper", symbols=["X"], timeframe="1day",
                        risk=RiskConfig(allow_fractional=True))
    storage = Storage(db)
    engine = Engine(settings, broker, data, STRATEGIES[name](), RiskManager(settings.risk),
                    storage=storage, mode_label="dry_run", enforce_live_ack=False)
    out = {}
    try:
        while True:
            line = engine.propose(10_000.0).lines[0]
            out[data.timestamp] = line.target
            if not data.has_next():
                return out
            data.advance(STRIDE)
    finally:
        storage.close()


@pytest.mark.parametrize("name", sorted(STRATEGIES))
def test_engine_strategy_verdict_equals_the_full_frame_backtest(name, tmp_path):
    """Every bar of five seeds: the verdict the engine acts on is the full-frame
    one the Backtester validated (it fails with the strategy given the fetch
    window: supertrend, rsi_reversion and macd_trend diverge)."""
    for seed in range(5):
        df = synthetic_ohlcv(PERIODS, seed=seed, freq="B", volatility=0.02)
        seen = _engine_verdicts(name, df, str(tmp_path / f"{seed}.db"))
        strategy = STRATEGIES[name]()
        full = strategy.target_positions(df)
        for ts, verdict in seen.items():
            i = df.index.get_loc(ts)
            expected = (strategy.latest_target(df.iloc[: i + 1]) if name in TAIL_BOUNDED
                        else int(full.iloc[i]))
            assert verdict == expected, (name, seed, ts)


def test_stored_history_is_read_back_bounded(tmp_path, monkeypatch):
    """The newest ``HISTORY_BARS`` bars, oldest first: memory stays bounded."""
    from tradebot.advisor import history
    from tradebot.engine import signals

    monkeypatch.setattr(signals, "HISTORY_BARS", 50)
    monkeypatch.setattr(history, "HISTORY_BARS", 50)
    df = synthetic_ohlcv(120, seed=1)
    with Storage(str(tmp_path / "t.db")) as store:
        store.record_bars("X", "1day", df, "paper")
        tail = store.load_bars("X", "1day", "paper", limit=50)
        assert list(tail.index) == list(df.index[-50:])
        engine = type("E", (), {"storage": store, "mode": "paper",
                                "settings": Settings(symbols=["X"], timeframe="1day")})()
        got = signals.history_frames(engine, {"X": df.iloc[-10:]})["X"]
        assert list(got.index) == list(df.index[-50:])
        assert list(history.bounded(df).index) == list(df.index[-50:])
