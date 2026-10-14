import numpy as np
import pandas as pd
import pytest

from tradebot.universe import AlpacaLiquidityUniverse, LiquidityScreen, build_universe


def _frame(price: float, volume: float, periods: int = 30) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=periods, freq="1D", tz="UTC")
    return pd.DataFrame(
        {"open": price, "high": price, "low": price,
         "close": price, "volume": volume},
        index=idx,
    )


def _pool():
    return {
        "BIG": _frame(price=100.0, volume=1_000_000),   # ADV 100M
        "MID": _frame(price=50.0, volume=100_000),      # ADV 5M
        "CHEAP": _frame(price=2.0, volume=10_000_000),  # ADV 20M but < $5
        "THIN": _frame(price=80.0, volume=1_000),       # ADV 80k, illiquid
        "STUB": _frame(price=90.0, volume=1_000_000, periods=5),  # short history
    }


def test_liquidity_screen_filters_and_ranks_by_adv():
    screen = LiquidityScreen(min_price=5.0, min_dollar_volume=1_000_000, window=20)
    assert screen.screen(_pool()) == ["BIG", "MID"]     # ADV order, survivors only


def test_liquidity_screen_max_symbols_caps_the_list():
    screen = LiquidityScreen(min_price=5.0, min_dollar_volume=1_000_000,
                             window=20, max_symbols=1)
    assert screen.screen(_pool()) == ["BIG"]


def test_liquidity_screen_details_expose_metrics():
    screen = LiquidityScreen(min_price=5.0, min_dollar_volume=1_000_000, window=20)
    rows = screen.details(_pool())
    assert rows[0]["symbol"] == "BIG"
    assert rows[0]["price"] == pytest.approx(100.0)
    assert rows[0]["adv"] == pytest.approx(100_000_000.0)


def test_universe_pipeline_with_injected_fetchers():
    pool = _pool()
    calls = {}

    def actives(top):
        calls["top"] = top
        return list(pool) + ["UNTRADABLE"]

    def tradable():
        return set(pool)                       # drops UNTRADABLE

    def bars(symbols):
        calls["bars_for"] = list(symbols)
        return {s: pool[s] for s in symbols}

    uni = AlpacaLiquidityUniverse(
        candidates=50, min_price=5.0, min_dollar_volume=1_000_000, window=20,
        max_symbols=10,
        actives_fetcher=actives, tradable_fetcher=tradable, bars_fetcher=bars,
    )
    assert uni.resolve() == ["BIG", "MID"]
    assert calls["top"] == 50
    assert "UNTRADABLE" not in calls["bars_for"]   # filtered before the fetch


def test_universe_resolution_without_creds_raises(monkeypatch):
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET", raising=False)
    uni = AlpacaLiquidityUniverse()
    with pytest.raises(RuntimeError, match="credentials"):
        uni.resolve()


def test_build_universe_registry():
    uni = build_universe("alpaca_liquidity", {"candidates": 25, "min_price": 10.0})
    assert isinstance(uni, AlpacaLiquidityUniverse)
    assert uni.candidates == 25
    assert uni.screen.min_price == 10.0
    with pytest.raises(KeyError):
        build_universe("dartboard")


def test_cli_universe_command(tmp_path, capsys, monkeypatch):
    from tradebot.cli import main
    from tradebot.config import Settings

    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "symbols: [SPY]\n"
        "universe:\n"
        "  source: alpaca_liquidity\n"
        "  params: {candidates: 10}\n"
    )

    # Without credentials the command explains itself and fails cleanly.
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET", raising=False)
    assert main(["universe", "--config", str(cfg)]) == 2
    assert "credentials" in capsys.readouterr().err

    # Happy path with a stubbed source.
    class _Stub:
        def resolve_details(self):
            return [{"symbol": "AAPL", "price": 190.0, "adv": 12_000_000_000.0}]

    monkeypatch.setattr(Settings, "build_universe", lambda self: _Stub())
    assert main(["universe", "--config", str(cfg)]) == 0
    out = capsys.readouterr().out
    assert "AAPL" in out and "1 candidates" in out

    # No universe block -> pointer to the config docs.
    plain = tmp_path / "plain.yaml"
    plain.write_text("symbols: [SPY]\n")
    monkeypatch.undo()
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET", raising=False)
    assert main(["universe", "--config", str(plain)]) == 2


def test_split_bars_frame_multiindex():
    from tradebot.data.alpaca_data import split_bars_frame

    idx = pd.MultiIndex.from_product(
        [["AAA", "BBB"], pd.date_range("2024-01-01", periods=3, freq="1D", tz="UTC")],
        names=["symbol", "timestamp"],
    )
    df = pd.DataFrame(
        {"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0,
         "volume": np.arange(6, dtype=float)},
        index=idx,
    )
    out = split_bars_frame(df, ["AAA", "BBB", "MISSING"])
    assert set(out) == {"AAA", "BBB"}
    assert len(out["AAA"]) == 3
    assert list(out["AAA"].columns) == ["open", "high", "low", "close", "volume"]
    assert out["AAA"].index.tz is not None

    # Flat index = single-symbol response; never fanned out to many symbols.
    flat = df.xs("AAA", level="symbol")
    assert list(split_bars_frame(flat, ["AAA"])) == ["AAA"]
    assert split_bars_frame(flat, ["AAA", "BBB"]) == {}
    assert split_bars_frame(pd.DataFrame(), ["AAA"]) == {}
