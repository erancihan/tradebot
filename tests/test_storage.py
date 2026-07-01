import sqlite3

from tradebot.broker.dryrun import DryRunBroker
from tradebot.config import Settings
from tradebot.data.replay import ReplayData
from tradebot.data.synthetic import synthetic_ohlcv
from tradebot.engine import Engine
from tradebot.risk import RiskConfig, RiskManager
from tradebot.storage import Storage
from tradebot.strategies import build_strategy


def _count_bars(path, mode=None):
    con = sqlite3.connect(path)
    try:
        if mode:
            return con.execute("SELECT COUNT(*) FROM bars WHERE mode = ?", (mode,)).fetchone()[0]
        return con.execute("SELECT COUNT(*) FROM bars").fetchone()[0]
    finally:
        con.close()


def test_record_bars_is_idempotent(tmp_path):
    db = str(tmp_path / "t.db")
    df = synthetic_ohlcv(periods=10, seed=1)
    with Storage(db) as st:
        st.record_bars("SPY", "1day", df, "paper")
        st.record_bars("SPY", "1day", df, "paper")        # duplicate timestamps
    assert _count_bars(db) == 10                            # de-duplicated


def test_engine_records_bars_when_storage_present(tmp_path):
    db = str(tmp_path / "t.db")
    df = synthetic_ohlcv(periods=60, seed=1)
    data = ReplayData.from_single(df, "DEMO", warmup=30)
    settings = Settings(mode="paper", symbols=["DEMO"], timeframe="1day",
                        strategy_name="sma_crossover", strategy_params={"fast": 5, "slow": 20})
    strategy = build_strategy(settings.strategy_name, settings.strategy_params)
    broker = DryRunBroker(data, timeframe="1day", initial_cash=10_000)
    storage = Storage(db)
    engine = Engine(settings, broker, data, strategy, RiskManager(RiskConfig()),
                    storage=storage, mode_label="dry_run", enforce_live_ack=False)

    engine.rebalance()
    data.advance()
    engine.rebalance()
    storage.close()

    assert _count_bars(db, mode="dry_run") > 0
