from pathlib import Path

import pytest

from tradebot.arena.scenario import Scenario
from tradebot.data.cache import BarCache
from tradebot.data.synthetic import synthetic_ohlcv, synthetic_regime_ohlcv

SCENARIOS_DIR = Path(__file__).resolve().parents[1] / "scenarios"


def test_synthetic_scenario_is_deterministic():
    a = Scenario(symbols=["A", "B"]).build_frames()
    b = Scenario(symbols=["A", "B"]).build_frames()
    assert set(a) == {"A", "B"}
    assert a["A"].equals(b["A"]) and a["B"].equals(b["B"])
    # Distinct per-symbol seeds -> different series.
    assert not a["A"].equals(a["B"])


def test_alpaca_scenario_uses_injected_fetcher(tmp_path):
    calls = []

    def fetch(symbol, timeframe, start, end):
        calls.append(symbol)
        return synthetic_ohlcv(periods=200, seed=len(symbol))

    sc = Scenario(source="alpaca", symbols=["AAA", "BBB"],
                  cache_dir=str(tmp_path), timeframe="1day")
    frames = sc.build_frames(fetcher=fetch)

    assert set(frames) == {"AAA", "BBB"}
    assert all(len(f) == 200 for f in frames.values())
    assert sorted(calls) == ["AAA", "BBB"]
    # Data was cached, so a second build needs no fetch.
    calls.clear()
    sc.build_frames(fetcher=fetch)
    assert calls == []


def test_alpaca_scenario_reuses_cache_offline(tmp_path):
    BarCache(tmp_path).store("AAA", "1day", synthetic_ohlcv(periods=150, seed=1))
    sc = Scenario(source="alpaca", symbols=["AAA"], cache_dir=str(tmp_path))

    def boom(*a):
        raise AssertionError("should not fetch when cache covers the request")

    frames = sc.build_frames(fetcher=boom)
    assert len(frames["AAA"]) == 150


def test_regime_generator_is_continuous_and_regime_shaped():
    regimes = [
        {"periods": 200, "drift": 0.0006, "volatility": 0.008},
        {"periods": 60, "drift": -0.004, "volatility": 0.035},
        {"periods": 140, "drift": 0.001, "volatility": 0.015},
    ]
    df = synthetic_regime_ohlcv(regimes, seed=5)
    assert len(df) == 400
    # Deterministic given the seed.
    assert df.equals(synthetic_regime_ohlcv(regimes, seed=5))
    # Price path is continuous: each open equals the previous close.
    assert (df["open"].iloc[1:].to_numpy() == df["close"].iloc[:-1].to_numpy()).all()
    # The crash segment is actually wilder than the calm one.
    rets = df["close"].pct_change()
    assert rets.iloc[200:260].std() > 2 * rets.iloc[:200].std()
    assert df["close"].iloc[259] < df["close"].iloc[199]      # and it goes down

    with pytest.raises(ValueError):
        synthetic_regime_ohlcv([])
    with pytest.raises(ValueError):
        synthetic_regime_ohlcv([{"periods": 0}])


def test_scenario_regimes_override_flat_synthetic_params(tmp_path):
    p = tmp_path / "regime.yaml"
    p.write_text(
        "name: r\nsource: synthetic\nsymbols: [A, B]\nseed: 3\n"
        "regimes:\n"
        "  - {periods: 50, drift: 0.001, volatility: 0.01}\n"
        "  - {periods: 30, drift: -0.002, volatility: 0.03}\n"
    )
    sc = Scenario.from_yaml(p)
    assert len(sc.regimes) == 2
    frames = sc.build_frames()
    assert set(frames) == {"A", "B"}
    assert all(len(f) == 80 for f in frames.values())
    # Per-symbol seed offsets still apply.
    assert not frames["A"].equals(frames["B"])


def test_symbol_overrides_give_the_pool_a_spread(tmp_path):
    p = tmp_path / "xs.yaml"
    p.write_text(
        "name: xs\nsource: synthetic\nsymbols: [WIN, MID, LOSE, WILD]\n"
        "periods: 400\nseed: 9\ndrift: 0.0002\nvolatility: 0.012\n"
        "symbol_overrides:\n"
        "  WIN: {drift: 0.002}\n"
        "  LOSE: {drift: -0.002}\n"
        "  WILD: {volatility: 0.03}\n"
    )
    sc = Scenario.from_yaml(p)
    frames = sc.build_frames()
    assert set(frames) == {"WIN", "MID", "LOSE", "WILD"}
    # Each override is judged against the same-seed baseline (identical noise
    # draws), where the drift/vol effect is guaranteed rather than luck.
    base = {s: synthetic_ohlcv(periods=400, seed=9 + i, drift=0.0002,
                               volatility=0.012)
            for i, s in enumerate(sc.symbols)}
    assert frames["WIN"]["close"].iloc[-1] > base["WIN"]["close"].iloc[-1]
    assert frames["LOSE"]["close"].iloc[-1] < base["LOSE"]["close"].iloc[-1]
    assert frames["MID"].equals(base["MID"])              # untouched symbol
    wild_vol = frames["WILD"]["close"].pct_change().std()
    assert wild_vol > 1.5 * base["WILD"]["close"].pct_change().std()


def test_shipped_scenario_library_loads_and_builds():
    yamls = sorted(SCENARIOS_DIR.glob("*.yaml"))
    names = {p.stem for p in yamls}
    assert {"bull_trend", "sideways_chop", "crash_recovery", "vol_spike"} <= names
    for path in yamls:
        sc = Scenario.from_yaml(path)
        if sc.source != "synthetic":
            continue    # the alpaca example needs credentials/cache
        frames = sc.build_frames()
        assert frames and all(len(f) > 0 for f in frames.values())


def test_from_yaml_parses_alpaca_fields(tmp_path):
    p = tmp_path / "s.yaml"
    p.write_text(
        "name: t\nsource: alpaca\nsymbols: [SPY]\ntimeframe: 1day\n"
        "start: '2023-01-01'\nend: '2024-01-01'\ncache_dir: /tmp/c\n"
        "risk: {max_position_pct: 0.5}\n"
    )
    sc = Scenario.from_yaml(p)
    assert sc.source == "alpaca" and sc.symbols == ["SPY"]
    assert sc.start == "2023-01-01" and sc.end == "2024-01-01"
    assert sc.cache_dir == "/tmp/c" and sc.risk.max_position_pct == 0.5
