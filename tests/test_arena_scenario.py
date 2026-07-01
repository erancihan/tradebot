import pytest

from tradebot.arena.scenario import Scenario
from tradebot.data.cache import BarCache
from tradebot.data.synthetic import synthetic_ohlcv


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
