import pandas as pd
import pytest

from tradebot.broker import DryRunBroker
from tradebot.cli import main
from tradebot.config import LIVE_CONFIRM_ENV, Settings
from tradebot.data import ReplayData
from tradebot.data.synthetic import synthetic_ohlcv
from tradebot.engine import Engine
from tradebot.models import Order, Side
from tradebot.risk import RiskConfig, RiskManager
from tradebot.strategies import build_strategy


class StubData:
    """A trivial data source returning a flat bar at a settable price."""

    def __init__(self, prices: dict[str, float]):
        self.prices = prices

    def history(self, symbol, timeframe=None, lookback=None):
        price = self.prices[symbol]
        idx = pd.date_range("2024-01-01", periods=3, freq="1D", tz="UTC")
        return pd.DataFrame(
            {"open": price, "high": price, "low": price, "close": price, "volume": 1000.0},
            index=idx,
        )


# --- DryRunBroker --------------------------------------------------------------

def test_dryrun_broker_simulates_a_fill():
    broker = DryRunBroker(StubData({"SPY": 100.0}), initial_cash=10_000, slippage_bps=0)
    oid = broker.submit(Order("SPY", 10, Side.BUY))
    assert oid == "dryrun-1"
    assert broker.position("SPY").qty == 10
    acct = broker.account()
    assert acct.is_paper is True
    assert acct.cash == 9_000            # 10_000 - 10*100
    assert acct.equity == 10_000         # 9_000 cash + 10 shares * 100
    assert "SPY" in broker.positions()


def test_dryrun_broker_marks_to_latest_price():
    data = StubData({"SPY": 100.0})
    broker = DryRunBroker(data, initial_cash=10_000, slippage_bps=0)
    broker.submit(Order("SPY", 10, Side.BUY))
    data.prices["SPY"] = 120.0           # price moves up
    assert broker.account().equity == 9_000 + 10 * 120


def test_dryrun_broker_books_realized_pnl_on_close():
    data = StubData({"SPY": 100.0})
    broker = DryRunBroker(data, initial_cash=10_000, slippage_bps=0)
    broker.submit(Order("SPY", 10, Side.BUY))
    data.prices["SPY"] = 110.0
    broker.submit(Order("SPY", 10, Side.SELL))
    s = broker.summary()
    assert s["realized_pnl"] == 100.0
    assert s["num_trades"] == 1
    assert s["open_positions"] == "none"
    assert broker.position("SPY").is_flat


def test_dryrun_broker_never_has_resting_orders():
    broker = DryRunBroker(StubData({"X": 50.0}), initial_cash=1_000)
    broker.cancel_all()  # must be a harmless no-op


# --- ReplayData ----------------------------------------------------------------

def test_replaydata_window_grows_and_terminates():
    df = synthetic_ohlcv(periods=10, seed=1)
    rd = ReplayData.from_single(df, "X", warmup=3)
    assert len(rd.history("X")) == 3
    steps = 0
    while rd.has_next():
        rd.advance()
        steps += 1
    assert steps == 7                    # 3 -> 10
    assert len(rd.history("X")) == 10
    assert rd.progress == (10, 10)


def test_replaydata_rejects_unknown_symbol():
    rd = ReplayData.from_single(synthetic_ohlcv(periods=5, seed=1), "X")
    with pytest.raises(KeyError):
        rd.history("Y")


# --- Engine integration (offline forward-test) ---------------------------------

def test_engine_dry_run_forward_test_offline():
    settings = Settings(
        mode="paper", symbols=["X"], initial_cash=10_000, timeframe="1day",
        strategy_name="sma_crossover", strategy_params={"fast": 5, "slow": 20},
    )
    strategy = build_strategy(settings.strategy_name, settings.strategy_params)
    risk = RiskManager(settings.risk)
    df = synthetic_ohlcv(periods=120, drift=0.003, volatility=0.005, seed=3)  # uptrend
    data = ReplayData.from_single(df, "X", warmup=strategy.required_history + 2)
    broker = DryRunBroker(data, timeframe="1day", initial_cash=10_000, slippage_bps=0)
    engine = Engine(
        settings, broker, data, strategy, risk,
        mode_label="dry_run", enforce_live_ack=False,
    )

    while True:
        engine.rebalance()
        if not data.has_next():
            break
        data.advance()

    # A trend-follower on a steady uptrend should have placed at least one order.
    assert broker._order_seq >= 1
    assert engine.mode == "dry_run"
    # Equity is internally consistent (cash + marked positions).
    assert broker.account().equity > 0


def test_engine_dry_run_with_allocator_splits_the_book():
    from tradebot.allocation import EqualWeight

    settings = Settings(
        mode="paper", symbols=["A", "B"], initial_cash=10_000, timeframe="1day",
        strategy_name="sma_crossover", strategy_params={"fast": 5, "slow": 20},
        risk=RiskConfig(max_position_pct=1.0, max_gross_exposure=1.0),
    )
    strategy = build_strategy(settings.strategy_name, settings.strategy_params)
    frames = {
        "A": synthetic_ohlcv(periods=120, drift=0.003, volatility=0.005, seed=3),
        "B": synthetic_ohlcv(periods=120, drift=0.003, volatility=0.005, seed=4),
    }
    data = ReplayData(frames, warmup=strategy.required_history + 2)
    broker = DryRunBroker(data, timeframe="1day", initial_cash=10_000, slippage_bps=0)
    engine = Engine(
        settings, broker, data, strategy, RiskManager(settings.risk),
        mode_label="dry_run", enforce_live_ack=False, allocator=EqualWeight(),
    )

    while True:
        engine.rebalance()
        if not data.has_next():
            break
        data.advance()

    # Both uptrending symbols end up held, each within an equal (~50%) share
    # of equity — the allocator split the book instead of double-allocating.
    positions = {s: p for s, p in broker.positions().items() if not p.is_flat}
    assert set(positions) == {"A", "B"}
    equity = broker.account().equity
    for sym, pos in positions.items():
        price = float(data.history(sym)["close"].iloc[-1])
        assert abs(pos.qty) * price <= 0.55 * equity


def test_engine_dry_run_with_selector_holds_only_the_winner():
    from tradebot.allocation import EqualWeight
    from tradebot.selection import MomentumSelector

    def linear(start, step, periods):
        vals = [start + step * i for i in range(periods)]
        idx = pd.date_range("2024-01-01", periods=periods, freq="1D", tz="UTC")
        return pd.DataFrame({"open": vals, "high": vals, "low": vals,
                             "close": vals, "volume": 1000.0}, index=idx)

    settings = Settings(
        mode="paper", symbols=["UP", "DOWN"], initial_cash=10_000, timeframe="1day",
        strategy_name="buy_and_hold",
        risk=RiskConfig(max_position_pct=1.0, max_gross_exposure=1.0,
                        allow_fractional=True),
    )
    strategy = build_strategy(settings.strategy_name)
    selector = MomentumSelector(lookback=20, skip=2, top_k=1)
    frames = {"UP": linear(100, 1.0, 80), "DOWN": linear(200, -0.9, 80)}
    data = ReplayData(frames, warmup=selector.required_history + 2)
    broker = DryRunBroker(data, timeframe="1day", initial_cash=10_000, slippage_bps=0)
    engine = Engine(
        settings, broker, data, strategy, RiskManager(settings.risk),
        mode_label="dry_run", enforce_live_ack=False,
        allocator=EqualWeight(), selector=selector,
    )

    while True:
        engine.rebalance()
        if not data.has_next():
            break
        data.advance()

    held = {s for s, p in broker.positions().items() if not p.is_flat}
    assert held == {"UP"}                       # the loser never enters the book
    assert broker.account().equity > 10_000     # and riding the winner paid


def test_engine_selector_sees_full_history_not_the_fetch_window(tmp_path):
    """The live selector must walk the accumulated bars, not the fetch window.

    `RankedSelector.membership` carries `held` from an empty set, so its verdict
    depends on where the frame starts. Feeding it the engine's bounded fetch
    window made live selection depend on when the process happened to start and
    diverge from the backtest that validated it. Bars are the source of truth,
    so the engine reads its own persisted history back.
    """
    from tradebot.selection import MomentumSelector
    from tradebot.storage import Storage

    seen: list[int] = []

    class _RecordingSelector(MomentumSelector):
        def latest_targets(self, frames):
            seen.append(max((len(f) for f in frames.values()), default=0))
            return super().latest_targets(frames)

    def linear(start, step, periods):
        vals = [start + step * i for i in range(periods)]
        idx = pd.date_range("2024-01-01", periods=periods, freq="1D", tz="UTC")
        return pd.DataFrame({"open": vals, "high": vals, "low": vals,
                             "close": vals, "volume": 1000.0}, index=idx)

    settings = Settings(
        mode="paper", symbols=["UP", "DOWN"], initial_cash=10_000, timeframe="1day",
        strategy_name="buy_and_hold",
        risk=RiskConfig(max_position_pct=1.0, max_gross_exposure=1.0,
                        allow_fractional=True),
    )
    selector = _RecordingSelector(lookback=20, skip=2, top_k=1)
    # Long enough that the accumulated history outgrows the fetch window.
    frames = {"UP": linear(100, 1.0, 220), "DOWN": linear(200, -0.9, 220)}
    data = ReplayData(frames, warmup=selector.required_history + 2)
    broker = DryRunBroker(data, timeframe="1day", initial_cash=10_000, slippage_bps=0)
    storage = Storage(str(tmp_path / "t.db"))
    engine = Engine(
        settings, broker, data, build_strategy(settings.strategy_name),
        RiskManager(settings.risk), mode_label="dry_run", enforce_live_ack=False,
        selector=selector, storage=storage,
    )

    while True:
        engine.rebalance()
        if not data.has_next():
            break
        data.advance()
    storage.close()

    window = engine._lookback_days()
    # The bounded fetch window caps out; the accumulated history keeps growing
    # past it, which is the whole point.
    assert max(seen) > window, (
        f"selector never saw more than the {window}-bar fetch window (max {max(seen)})")
    assert seen == sorted(seen), "history handed to the selector must only grow"


def test_live_config_with_dry_run_skips_live_gate(monkeypatch):
    monkeypatch.delenv(LIVE_CONFIRM_ENV, raising=False)
    settings = Settings(mode="live", symbols=["X"])
    data = ReplayData.from_single(synthetic_ohlcv(periods=60, seed=1), "X", warmup=30)
    broker = DryRunBroker(data, initial_cash=10_000)
    strategy = build_strategy("sma_crossover")
    risk = RiskManager(RiskConfig())

    # Dry-run must NOT trip the live-money gate...
    Engine(settings, broker, data, strategy, risk,
           mode_label="dry_run", enforce_live_ack=False)
    # ...but the default (enforcing) path still does.
    with pytest.raises(PermissionError):
        Engine(settings, broker, data, strategy, risk)


# --- CLI end-to-end (no credentials, no network) -------------------------------

def test_cli_run_replay_is_fully_offline(tmp_path, capsys):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "mode: paper\n"
        "symbols: [X]\n"
        "timeframe: 1day\n"
        "initial_cash: 10000\n"
        f"db_path: {tmp_path / 'dry.db'}\n"
        "strategy:\n"
        "  name: sma_crossover\n"
        "  params: {fast: 5, slow: 20}\n"
    )
    rc = main(["run", "--config", str(cfg), "--replay", "--replay-periods", "80"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "[DRY-RUN]" in out
    assert "Dry-run forward-test summary" in out
