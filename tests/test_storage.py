import sqlite3

import pytest

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


def test_rewriting_a_bar_updates_it(tmp_path):
    """The engine persists today's still-forming bar; the settled one must win.

    Under the old INSERT OR IGNORE the first (partial) write was frozen forever,
    and since the stored history feeds the selector that contamination sat on
    the decision path.
    """
    import sqlite3

    db = str(tmp_path / "t.db")
    df = synthetic_ohlcv(periods=10, seed=1)
    settled = df.copy()
    settled.iloc[-1, settled.columns.get_loc("close")] = 999.0

    with Storage(db) as st:
        st.record_bars("SPY", "1day", df, "paper")
        st.record_bars("SPY", "1day", settled, "paper")

    assert _count_bars(db) == 10                            # still no duplicates
    conn = sqlite3.connect(db)
    last = conn.execute(
        "SELECT close FROM bars WHERE symbol='SPY' ORDER BY ts DESC LIMIT 1"
    ).fetchone()[0]
    conn.close()
    assert last == 999.0                                    # latest write wins


def test_target_weights_round_trip(tmp_path):
    db = str(tmp_path / "t.db")
    with Storage(db) as st:
        st.record_weights({"SPY": 0.6, "QQQ": 0.4}, "paper")
        st.record_weights({"SPY": 0.5, "QQQ": 0.5}, "paper")   # newer pass wins
        st.record_weights({"IWM": 1.0}, "dry_run")
        assert st.latest_weights("paper") == {"SPY": 0.5, "QQQ": 0.5}
        assert st.latest_weights("dry_run") == {"IWM": 1.0}
        assert st.latest_weights() != {}
        st.record_weights({}, "paper")                          # no-op, keeps latest
        assert st.latest_weights("paper") == {"SPY": 0.5, "QQQ": 0.5}


def test_universe_snapshot_round_trip(tmp_path):
    db = str(tmp_path / "t.db")
    with Storage(db) as st:
        st.record_universe(["AAPL", "MSFT"], "paper")
        st.record_universe(["AAPL", "NVDA", "TSLA"], "paper")   # newest wins
        assert st.latest_universe("paper") == ["AAPL", "NVDA", "TSLA"]
        assert st.latest_universe("dry_run") == []
        st.record_universe([], "paper")                          # no-op
        assert st.latest_universe("paper") == ["AAPL", "NVDA", "TSLA"]


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


# --- the order log's price column ----------------------------------------------

_OLD_ORDERS = """CREATE TABLE orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, symbol TEXT NOT NULL,
    side TEXT NOT NULL, qty REAL NOT NULL, type TEXT NOT NULL,
    broker_order_id TEXT, mode TEXT NOT NULL)"""


def test_an_order_log_without_a_price_column_migrates_on_open(tmp_path):
    """A database written before `orders.price` existed opens, keeps its rows
    (price NULL: never guessed) and accepts priced orders afterwards."""
    from tradebot.models import Order, Side

    db = str(tmp_path / "old.db")
    con = sqlite3.connect(db)
    con.execute(_OLD_ORDERS)
    con.execute("INSERT INTO orders (ts, symbol, side, qty, type, broker_order_id, mode)"
                " VALUES ('2025-01-02T00:00:00+00:00', 'SPY', 'buy', 3, 'market', NULL, 'paper')")
    con.commit()
    con.close()

    with Storage(db) as st:
        st.record_order(Order(symbol="QQQ", qty=2, side=Side.BUY), "o-2", "paper", price=401.5)
    with Storage(db):                                   # a second open is a no-op
        pass
    con = sqlite3.connect(db)
    rows = con.execute("SELECT symbol, qty, price FROM orders ORDER BY id").fetchall()
    con.close()
    assert rows == [("SPY", 3.0, None), ("QQQ", 2.0, 401.5)]


def _buying_engine(db: str, storage: Storage) -> Engine:
    data = ReplayData.from_single(synthetic_ohlcv(periods=60, seed=1), "DEMO", warmup=30)
    settings = Settings(mode="paper", symbols=["DEMO"], timeframe="1day",
                        strategy_name="buy_and_hold", strategy_params={})
    strategy = build_strategy(settings.strategy_name, settings.strategy_params)
    broker = DryRunBroker(data, timeframe="1day", initial_cash=10_000)
    return Engine(settings, broker, data, strategy, RiskManager(RiskConfig()),
                  storage=storage, mode_label="dry_run", enforce_live_ack=False)


def _logged_prices(db: str) -> dict[str, float]:
    con = sqlite3.connect(db)
    try:
        return dict(con.execute("SELECT symbol, price FROM orders").fetchall())
    finally:
        con.close()


def test_the_engine_logs_the_price_each_order_was_sized_at(tmp_path):
    db = str(tmp_path / "t.db")
    with Storage(db) as storage:
        outcome = _buying_engine(db, storage).step()
    sized = {ln.symbol: ln.price for ln in outcome.proposal.lines if ln.order_qty}
    assert sized and _logged_prices(db) == sized


def test_an_approved_line_logs_the_price_it_was_parked_at(tmp_path):
    db = str(tmp_path / "t.db")
    with Storage(db) as storage:
        engine = _buying_engine(db, storage)
        engine.step(submit=False)
        pending = storage.pending_lines("dry_run")
        engine.submit_lines([ln["id"] for ln in pending])
    assert pending and _logged_prices(db) == {ln["symbol"]: ln["price"] for ln in pending}


class _RacedConnection:
    """A connection whose column check is answered just before another opener
    adds the column: both saw it missing, so this one's ALTER collides."""

    def __init__(self, db: str) -> None:
        self.real = sqlite3.connect(db)
        self.db = db
        self.raced = False

    def execute(self, sql: str, *args):
        if sql.startswith("PRAGMA table_info(orders)") and not self.raced:
            stale = self.real.execute(sql, *args).fetchall()
            self.raced = True
            other = sqlite3.connect(self.db)          # the concurrent Storage() open
            other.execute("ALTER TABLE orders ADD COLUMN price REAL")
            other.commit()
            other.close()
            return iter(stale)
        return self.real.execute(sql, *args)

    def commit(self) -> None:
        self.real.commit()


def test_two_openers_migrating_at_once_both_succeed(tmp_path):
    from tradebot.storage.schema import migrate

    db = str(tmp_path / "old.db")
    con = sqlite3.connect(db)
    con.execute(_OLD_ORDERS)
    con.commit()
    con.close()
    raced = _RacedConnection(db)
    migrate(raced)                                    # the loser of the race
    assert raced.raced
    cols = [r[1] for r in raced.real.execute("PRAGMA table_info(orders)")]
    assert cols.count("price") == 1
    raced.real.close()


def test_a_migration_error_that_is_not_the_race_still_raises(tmp_path, monkeypatch):
    from tradebot.storage import schema

    monkeypatch.setattr(schema, "_ADDED_COLUMNS", (("orders", "price", "REAL NOT NULL"),))
    db = str(tmp_path / "old.db")
    con = sqlite3.connect(db)
    con.execute(_OLD_ORDERS)
    con.execute("INSERT INTO orders (ts, symbol, side, qty, type, mode)"
                " VALUES ('t', 'SPY', 'buy', 1, 'market', 'paper')")
    con.commit()
    with pytest.raises(sqlite3.OperationalError):
        schema.migrate(con)
    con.close()
