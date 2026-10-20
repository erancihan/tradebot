"""The list is the mandate, within limits: live never sells what it did not
buy, ``manage_unlisted`` switches it off, the CLI trades the web's list, one
unpriceable position never unprices the rest, and a swap sells first."""

from __future__ import annotations

import logging

import pandas as pd
import pytest

from tradebot.advisor.unlisted import off_list
from tradebot.broker import DryRunBroker
from tradebot.cli import main
from tradebot.config import LIVE_CONFIRM_ENV, LIVE_CONFIRM_VALUE, Settings
from tradebot.data import ReplayData
from tradebot.data.synthetic import synthetic_ohlcv
from tradebot.engine import Engine
from tradebot.engine.unlisted import read_unlisted
from tradebot.models import Order, Side
from tradebot.risk import RiskConfig, RiskManager
from tradebot.storage import Storage
from tradebot.storage.watchlist import active_symbols, resolve_active
from tradebot.strategies import build_strategy


def _engine(tmp_path, settings, **kw):
    frames = {s: synthetic_ohlcv(periods=60, seed=i) for i, s in enumerate(("SPY", "QQQ", "IWM"))}
    data = ReplayData(frames, warmup=40)
    broker = DryRunBroker(data, initial_cash=10_000, slippage_bps=0)
    broker.submit(Order(symbol="IWM", qty=5, side=Side.BUY))
    engine = Engine(settings, broker, data, build_strategy("buy_and_hold"),
                    RiskManager(RiskConfig()), storage=Storage(tmp_path / "t.db"), **kw)
    return engine, broker


# --- H1: live never manages unlisted names; the flag switches it off ------------

def test_live_never_sells_a_name_it_did_not_buy(tmp_path, monkeypatch):
    monkeypatch.setenv(LIVE_CONFIRM_ENV, LIVE_CONFIRM_VALUE)
    settings = Settings(mode="live", symbols=["SPY", "QQQ"])
    assert settings.manage_unlisted          # the flag is on: live still refuses
    engine, broker = _engine(tmp_path, settings)
    assert engine.mode == "live"
    assert read_unlisted(engine) is None
    actions = {a.symbol for a in engine.rebalance()}
    assert "IWM" not in actions and broker.position("IWM").qty == 5
    assert "IWM" not in {ln.symbol for ln in engine.propose(10_000.0).lines}


def test_a_live_settings_file_under_a_dry_run_label_still_refuses(tmp_path):
    engine, _ = _engine(tmp_path, Settings(mode="live", symbols=["SPY"]),
                        mode_label="dry_run", enforce_live_ack=False)
    assert read_unlisted(engine) is None


def test_manage_unlisted_false_leaves_an_off_list_holding_alone(tmp_path):
    engine, broker = _engine(tmp_path, Settings(mode="paper", symbols=["SPY", "QQQ"],
                                                manage_unlisted=False),
                             mode_label="dry_run", enforce_live_ack=False)
    assert "IWM" not in {ln.symbol for ln in engine.propose(10_000.0).lines}
    assert "IWM" not in {a.symbol for a in engine.rebalance()}
    assert broker.position("IWM").qty == 5


def test_manage_unlisted_reads_from_yaml_and_defaults_on():
    assert Settings.from_dict({}).manage_unlisted is True
    assert Settings.from_dict({"manage_unlisted": False}).manage_unlisted is False


# --- H1(c): the CLI trades the web's list -------------------------------------

def test_core_and_web_resolvers_are_one(tmp_path):
    pytest.importorskip("fastapi")
    from tradebot.web.services import symbols_service

    settings = Settings(symbols=["SPY", "QQQ"])
    with Storage(tmp_path / "t.db") as store:
        assert resolve_active(settings, store) == {"symbols": ["SPY", "QQQ"], "source": "config"}
        store.add_to_watchlist(["IWM", "DIA"])
        assert symbols_service.resolve(settings, store) == resolve_active(settings, store)
        assert symbols_service.active_symbols(settings, store) == ["IWM", "DIA"]
        assert active_symbols(settings, store) == ["IWM", "DIA"]
        assert symbols_service.with_active_symbols(settings, store).symbols == ["IWM", "DIA"]


def _run_replay(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text(
        f"symbols: [SPY, QQQ]\ndb_path: {tmp_path / 't.db'}\nstrategy: {{name: buy_and_hold}}\n")
    assert main(["run", "--replay", "--replay-periods", "60"]) == 0
    return capsys.readouterr()


def test_cli_run_trades_the_watchlist_when_the_db_has_one(tmp_path, monkeypatch, capsys):
    with Storage(tmp_path / "t.db") as store:
        store.add_to_watchlist(["IWM", "DIA", "TLT"])
    out = _run_replay(tmp_path, monkeypatch, capsys)
    assert "symbols=watchlist(3)" in out.err
    with Storage(tmp_path / "t.db") as store:
        traded = {r["symbol"] for r in store._conn.execute("SELECT symbol FROM orders")}
    assert traded == {"IWM", "DIA", "TLT"}


def test_cli_run_says_config_without_a_watchlist(tmp_path, monkeypatch, capsys):
    assert "symbols=config(2)" in _run_replay(tmp_path, monkeypatch, capsys).err


def test_cli_and_web_open_the_same_trading_db(tmp_path, monkeypatch, capsys):
    """Flag, then ``$TRADEBOT_DB``, then ``db_path``: one rule for both."""
    from tradebot.config import trading_db_path

    monkeypatch.setenv("TRADEBOT_DB", str(tmp_path / "env.db"))
    with Storage(tmp_path / "env.db") as store:
        store.add_to_watchlist(["IWM", "DIA"])           # the web's watchlist
    out = _run_replay(tmp_path, monkeypatch, capsys)
    assert "symbols=watchlist(2)" in out.err and f"db={tmp_path / 'env.db'}" in out.err
    assert not (tmp_path / "t.db").exists()             # db_path lost to the env
    settings = Settings(db_path=str(tmp_path / "t.db"))
    assert trading_db_path(settings) == str(tmp_path / "env.db")
    assert trading_db_path(settings, "flag.db") == "flag.db"
    pytest.importorskip("fastapi")
    from tradebot.web.app import create_app

    app = create_app(arena_db=str(tmp_path / "a.db"),
                     settings_path=str(tmp_path / "config.yaml"))
    assert app.state.trading_db == str(tmp_path / "env.db")
    assert main(["run", "--replay", "--replay-periods", "60",
                 "--trading-db", str(tmp_path / "flag.db")]) == 0
    assert f"db={tmp_path / 'flag.db'}" in capsys.readouterr().err
    assert (tmp_path / "flag.db").exists()


def test_a_running_engine_sees_a_watchlist_edit_on_its_next_pass(tmp_path, caplog):
    """The CLI loop is not reset by a web edit: the engine re-reads the list."""
    engine, broker = _engine(tmp_path, Settings(mode="paper", symbols=["SPY", "QQQ"]),
                             mode_label="dry_run", enforce_live_ack=False)
    engine.rebalance()
    assert broker.position("QQQ").qty > 0 and broker.position("IWM").qty == 0
    engine.storage.add_to_watchlist(["SPY", "IWM"])      # edited on the phone
    with caplog.at_level(logging.INFO, logger="tradebot.engine"):
        lines = {ln.symbol: ln for ln in engine.propose(10_000.0).lines}
        engine.propose(10_000.0)
    assert lines["IWM"].action == "buy"                  # added: proposed
    assert lines["QQQ"].action == "sell" and lines["QQQ"].desired_qty == 0   # removed: flat
    assert caplog.text.count("symbols=watchlist(2)") == 1                   # once per change
    engine.storage.remove_from_watchlist(["SPY", "IWM"])
    assert engine.propose(10_000.0) and engine.settings.symbols == ["SPY", "QQQ"]


def test_an_engine_without_storage_trades_the_config_list(tmp_path):
    frames = {s: synthetic_ohlcv(periods=60, seed=i) for i, s in enumerate(("SPY", "QQQ"))}
    data = ReplayData(frames, warmup=40)
    engine = Engine(Settings(mode="paper", symbols=["SPY", "QQQ"]),
                    DryRunBroker(data, initial_cash=10_000), data,
                    build_strategy("buy_and_hold"), RiskManager(RiskConfig()),
                    mode_label="dry_run", enforce_live_ack=False)
    assert {ln.symbol for ln in engine.propose(10_000.0).lines} == {"SPY", "QQQ"}


# --- M1: one unpriceable position never unprices the rest ----------------------

class _PickyData:
    """A stock-data source: ``history_many`` fails if any symbol in the batch
    is not a stock it knows, and ``history`` fails only for that symbol."""

    STOCKS = {"IWM", "BRK.B"}

    def __init__(self):
        self.asked: list[str] = []

    def history_many(self, symbols, timeframe=None, lookback=None):
        if not set(symbols) <= self.STOCKS:
            raise ValueError("invalid symbol in batch")
        return {s: self.history(s) for s in symbols}

    def history(self, symbol, timeframe=None, lookback=None):
        self.asked.append(symbol)
        if symbol not in self.STOCKS:
            raise ValueError(f"no such stock: {symbol}")
        idx = pd.date_range("2024-01-01", periods=3, freq="1D", tz="UTC")
        return pd.DataFrame({"close": [10.0, 11.0, 12.0]}, index=idx)


class _Holds:
    def __init__(self, held, kinds=None):
        self.held, self.kinds = held, kinds or {}

    def positions(self):
        return {s: type("P", (), {"qty": q, "asset_class": self.kinds.get(s, "us_equity")})()
                for s, q in self.held.items()}


class _FakeEngine:
    def __init__(self, held, data, symbols=("SPY",), kinds=None):
        self.broker, self.data, self.mode = _Holds(held, kinds), data, "paper"
        self.settings = Settings(mode="paper", symbols=list(symbols))


def test_a_crypto_position_is_ignored_and_the_rest_are_priced(caplog):
    data = _PickyData()
    engine = _FakeEngine({"IWM": 5.0, "BTC/USD": 0.5, "BTCUSD": 0.5, "BRK.B": 2.0}, data)
    with caplog.at_level(logging.INFO, logger="tradebot.advisor"):
        got = read_unlisted(engine)
    # "BTC/USD" is not an equity ticker: never fetched, never sized.
    assert "BTC/USD" not in got and "BTC/USD" not in data.asked
    assert "Ignoring BTC/USD" in caplog.text
    # "BTCUSD" looks like a ticker, so the batch fails on it; the fallback
    # fetches each name, so it alone goes unpriced (a skipped line).
    assert got == {"IWM": (5.0, 12.0), "BRK.B": (2.0, 12.0), "BTCUSD": (0.5, None)}


def test_a_position_of_another_asset_class_is_not_an_off_list_holding():
    """Alpaca names crypto `BTCUSD`, a valid-looking ticker: the asset class,
    not the symbol, keeps it out, so it is never fetched or skipped again."""
    data = _PickyData()
    engine = _FakeEngine({"IWM": 5.0, "BTCUSD": 0.5}, data, kinds={"BTCUSD": "crypto"})
    assert read_unlisted(engine) == {"IWM": (5.0, 12.0)}
    assert "BTCUSD" not in data.asked


def test_alpaca_positions_carry_the_asset_class():
    from tradebot.broker.alpaca_broker import AlpacaBroker

    class _Enum:
        value = "crypto"

    raw = [type("P", (), {"symbol": "BTCUSD", "qty": "0.5", "avg_entry_price": "60000",
                          "asset_class": _Enum()})(),
           type("P", (), {"symbol": "SPY", "qty": "13", "avg_entry_price": "767.24"})()]
    broker = AlpacaBroker.__new__(AlpacaBroker)
    broker._client = type("C", (), {"get_all_positions": staticmethod(lambda: raw)})()
    got = broker.positions()
    assert got["BTCUSD"].asset_class == "crypto"
    assert got["SPY"].asset_class == "us_equity"


def test_off_list_ignores_non_equity_symbols():
    assert off_list({"IWM": 1.0, "BTC/USD": 1.0, "AAPL240119C00150000": 1.0}, ["SPY"]) == {
        "IWM": 1.0}


# --- L4: symbol case -------------------------------------------------------------

def test_lower_case_config_symbols_match_the_brokers():
    settings = Settings.from_dict({"symbols": [" spy", "qqq "]})
    assert settings.symbols == ["SPY", "QQQ"]
    assert off_list({"SPY": 3.0, "IWM": 1.0}, ["spy"]) == {"IWM": 1.0}


def test_a_config_symbol_that_is_not_a_symbol_fails_to_load():
    """Every path sees a clean list: nothing is dropped and then sold as unlisted."""
    with pytest.raises(ValueError, match="bad symbol") as err:
        Settings.from_dict({"symbols": ["spy", "bad symbol", "QQQ"]})
    assert "SPY" not in str(err.value)
    assert Settings.from_yaml("config.example.yaml").symbols


# --- L1: a swap sells before it buys ----------------------------------------------

class _StrictBroker(DryRunBroker):
    """Rejects a buy the cash cannot cover, as a cash account would."""

    def submit(self, order) -> str:
        if order.side is Side.BUY:
            price = self._latest_price(order.symbol)
            if order.qty * price > self.account().cash + 1e-6:
                raise RuntimeError("insufficient buying power")
        return super().submit(order)


def _flat(periods=60):
    idx = pd.date_range("2024-01-01", periods=periods, freq="1D", tz="UTC")
    return pd.DataFrame({c: 100.0 for c in ("open", "high", "low", "close")} | {"volume": 1e3},
                        index=idx)


def _swap_engine(tmp_path):
    data = ReplayData({"QQQ": _flat(), "IWM": _flat()}, warmup=40)
    broker = _StrictBroker(data, initial_cash=10_000, slippage_bps=0)
    broker.submit(Order(symbol="QQQ", qty=95, side=Side.BUY))        # cash 500 left
    engine = Engine(Settings(mode="paper", symbols=["IWM"]), broker, data,
                    build_strategy("buy_and_hold"), RiskManager(RiskConfig(max_position_pct=0.5)),
                    storage=Storage(tmp_path / "t.db"), mode_label="dry_run",
                    enforce_live_ack=False)
    return engine, broker


def test_an_automatic_swap_sells_first_and_completes_in_one_pass(tmp_path):
    engine, broker = _swap_engine(tmp_path)
    proposal = engine.propose(10_000.0)
    assert [ln.symbol for ln in proposal.lines] == ["IWM", "QQQ"]   # display order kept
    engine.rebalance()
    assert broker.position("QQQ").is_flat and broker.position("IWM").qty == 50


def test_an_approved_swap_sells_first_too(tmp_path):
    engine, broker = _swap_engine(tmp_path)
    engine.step(submit=False)
    ids = [ln["id"] for ln in engine.storage.pending_lines("dry_run")]
    engine.submit_lines(ids)
    assert broker.position("QQQ").is_flat and broker.position("IWM").qty == 50


class _Flattenable:
    """A broker holding an equity and a hand-bought crypto position."""

    def __init__(self):
        self.sent: list[Order] = []

    def cancel_all(self):
        pass

    def positions(self):
        from tradebot.models import Position

        return {"SPY": Position("SPY", 4.0, 100.0),
                "BTCUSD": Position("BTCUSD", 0.5, 60000.0, asset_class="crypto")}

    def submit(self, order):
        self.sent.append(order)
        return f"o-{order.symbol}"


def test_the_daily_loss_flatten_closes_equities_only():
    """A hand-held crypto position is never the bot's to sell."""
    from tradebot.engine.session import flatten

    broker = _Flattenable()
    engine = type("E", (), {"broker": broker, "storage": None, "mode": "paper"})()
    assert flatten(engine) == ["SPY"]
    assert [o.symbol for o in broker.sent] == ["SPY"]


def test_is_equity_reads_the_asset_class():
    from tradebot.models import Position, is_equity

    assert is_equity(Position("SPY", 1.0))
    assert not is_equity(Position("BTCUSD", 1.0, asset_class="crypto"))
    assert is_equity(type("P", (), {"qty": 1.0})())      # no class: an equity


def test_orders_record_why_they_were_sent(tmp_path):
    """``orders.intent``: an entry opens or grows exposure, anything else
    (a reduction, an off-list close, a daily-loss flatten) is an exit."""
    from types import SimpleNamespace

    from tradebot.engine.orders import submit_line
    from tradebot.engine.session import flatten

    broker = _Flattenable()
    with Storage(tmp_path / "t.db") as st:
        engine = SimpleNamespace(broker=broker, storage=st, mode="paper",
                                 risk=RiskManager(RiskConfig()), _notify=lambda e: None)
        def line(cur, delta):
            return SimpleNamespace(symbol="SPY", target=1, order_qty=delta, price=100.0,
                                   current_qty=cur, desired_qty=cur + delta)
        submit_line(engine, line(0.0, 5.0))           # opens
        submit_line(engine, line(5.0, -2.0))          # reduces
        submit_line(engine, line(3.0, -6.0))          # flips: opens a short
        flatten(engine)
        got = [tuple(r) for r in st._conn.execute(
            "SELECT side, qty, intent FROM orders ORDER BY id")]
    assert got == [("buy", 5.0, "entry"), ("sell", 2.0, "exit"), ("sell", 6.0, "entry"),
                   ("sell", 4.0, "exit")]


def test_manages_unlisted_for_is_the_one_rule_without_an_engine():
    from tradebot.engine.unlisted import manages_unlisted_for

    assert manages_unlisted_for("paper", Settings(mode="paper")) is True
    assert manages_unlisted_for("paper", Settings(mode="paper", manage_unlisted=False)) is False
    assert manages_unlisted_for("live", Settings(mode="paper")) is False
    assert manages_unlisted_for("paper", Settings(mode="live")) is False
