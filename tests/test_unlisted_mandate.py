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
