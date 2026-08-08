import time

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from tradebot.web.app import create_app  # noqa: E402


def _client(tmp_path):
    return TestClient(create_app(trading_db=str(tmp_path / "t.db"),
                                 arena_db=str(tmp_path / "a.db"),
                                 cache_dir=str(tmp_path / "cache")))


def _seed_cache(tmp_path, symbol="XLTEST", timeframe="1day", periods=120):
    """Put a real-shaped frame in the web app's bar cache, manifest included."""
    from tradebot.data.cache import BarCache
    from tradebot.data.synthetic import synthetic_ohlcv

    cache = BarCache(tmp_path / "cache")
    df = synthetic_ohlcv(periods=periods, seed=7)
    cache.store(symbol, timeframe, df)
    cache.record_coverage(symbol, timeframe, df.index.min(), df.index.max())
    return df


def _wait(client, job_id, timeout=15.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["state"] in ("done", "error"):
            return job
        time.sleep(0.05)
    raise AssertionError("job did not finish in time")


def test_backtest_job_runs_to_completion(tmp_path):
    client = _client(tmp_path)
    r = client.post("/api/jobs", json={
        "kind": "backtest", "strategy": "sma_crossover", "periods": 200,
        "seed": 1, "initial_cash": 10000, "params": {"fast": 5, "slow": 20},
    })
    assert r.status_code == 200
    job = _wait(client, r.json()["job_id"])
    assert job["state"] == "done"
    assert "total_return" in job["summary"]
    assert len(job["equity"]["equity"]) > 0


def test_dryrun_job_produces_equity_curve(tmp_path):
    client = _client(tmp_path)
    r = client.post("/api/jobs", json={
        "kind": "dryrun", "strategy": "rsi_reversion", "periods": 150,
        "seed": 2, "initial_cash": 10000, "params": {"period": 14, "oversold": 30},
    })
    job = _wait(client, r.json()["job_id"])
    assert job["state"] == "done"
    assert "final_equity" in job["summary"]
    assert len(job["equity"]["index"]) == len(job["equity"]["equity"]) > 0


def test_invalid_kind_is_rejected(tmp_path):
    assert _client(tmp_path).post("/api/jobs", json={"kind": "nope"}).status_code == 400


def test_unknown_job_is_404(tmp_path):
    assert _client(tmp_path).get("/api/jobs/doesnotexist").status_code == 404


def test_bad_strategy_job_reports_error(tmp_path):
    client = _client(tmp_path)
    r = client.post("/api/jobs", json={"kind": "backtest", "strategy": "no_such_strategy"})
    job = _wait(client, r.json()["job_id"])
    assert job["state"] == "error"
    assert job["error"]


def test_run_page_renders(tmp_path):
    r = _client(tmp_path).get("/run")
    assert r.status_code == 200
    assert "Run a simulation" in r.text


def test_run_page_offers_both_data_sources_and_labels_results(tmp_path):
    text = _client(tmp_path).get("/run").text
    assert "Data source" in text
    assert "Cached real bars" in text
    assert "provenanceLabel" in text        # the badge that travels with results
    assert "pullHint" in text               # the never-fetch fallback command


# --- the cache inventory the Run page's "real data" mode is fed from ----------

def test_cache_endpoint_lists_cached_symbols_with_coverage(tmp_path):
    df = _seed_cache(tmp_path, symbol="XLTEST", periods=120)
    r = _client(tmp_path).get("/api/cache")
    assert r.status_code == 200
    entries = r.json()
    assert len(entries) == 1
    entry = entries[0]
    assert entry["symbol"] == "XLTEST"
    assert entry["timeframe"] == "1day"
    assert entry["bars"] == 120
    assert entry["first"].startswith(str(df.index.min().date()))
    assert entry["last"].startswith(str(df.index.max().date()))
    assert len(entry["coverage"]) == 1


def test_cache_endpoint_is_empty_when_nothing_cached(tmp_path):
    r = _client(tmp_path).get("/api/cache")
    assert r.status_code == 200
    assert r.json() == []


# --- the strategy catalog the Run page's dropdown is fed from -----------------

def test_strategies_endpoint_exposes_the_whole_registry(tmp_path):
    from tradebot.strategies import STRATEGIES

    r = _client(tmp_path).get("/api/strategies")
    assert r.status_code == 200
    specs = {s["name"]: s for s in r.json()}
    assert set(specs) == set(STRATEGIES)

    sma = {p["name"]: p for p in specs["sma_crossover"]["params"]}
    assert sma["fast"] == {"name": "fast", "type": "int", "default": 20}
    assert sma["slow"]["default"] == 50

    donchian = {p["name"]: p for p in specs["donchian_breakout"]["params"]}
    assert donchian["allow_short"] == {"name": "allow_short", "type": "bool",
                                       "default": False}

    rsi = {p["name"]: p for p in specs["rsi_reversion"]["params"]}
    assert rsi["oversold"]["type"] == "float"


def test_strategy_catalog_skips_params_a_form_cannot_express(tmp_path):
    r = _client(tmp_path).get("/api/strategies")
    specs = {s["name"]: s for s in r.json()}
    leader_params = [p["name"] for p in specs["follow_leader"]["params"]]
    assert "window" in leader_params          # simple int: exposed
    assert "strategies" not in leader_params  # a roster is not a form field
    vote_params = [p["name"] for p in specs["ensemble_vote"]["params"]]
    assert "strategies" not in vote_params
    assert "min_agree" not in vote_params     # None default = derived, not a knob


# --- real-data jobs: the cache, not the network -------------------------------

def test_real_backtest_job_runs_offline_from_the_cache(tmp_path):
    df = _seed_cache(tmp_path, symbol="XLTEST", periods=150)
    client = _client(tmp_path)
    r = client.post("/api/jobs", json={
        "kind": "backtest", "strategy": "sma_crossover",
        "source": "real", "symbol": "XLTEST",
        "start": str(df.index.min().date()), "end": str(df.index.max().date()),
        "initial_cash": 10000, "params": {"fast": 5, "slow": 20},
    })
    assert r.status_code == 200
    job = _wait(client, r.json()["job_id"])
    assert job["state"] == "done"
    prov = job["provenance"]
    assert prov["source"] == "real"
    assert prov["symbol"] == "XLTEST"
    assert prov["bars"] == 150
    assert "unadjusted" in prov["note"]
    assert len(job["equity"]["equity"]) > 0


def test_real_dryrun_job_runs_offline_from_the_cache(tmp_path):
    df = _seed_cache(tmp_path, symbol="XLTEST", periods=120)
    client = _client(tmp_path)
    r = client.post("/api/jobs", json={
        "kind": "dryrun", "strategy": "rsi_reversion",
        "source": "real", "symbol": "XLTEST",
        "start": str(df.index.min().date()), "end": str(df.index.max().date()),
        "params": {"period": 14, "oversold": 30},
    })
    job = _wait(client, r.json()["job_id"])
    assert job["state"] == "done"
    assert job["provenance"]["source"] == "real"
    assert len(job["equity"]["index"]) == len(job["equity"]["equity"]) > 0


def test_real_job_without_cached_bars_reports_the_exact_pull_command(tmp_path):
    client = _client(tmp_path)                     # nothing seeded
    r = client.post("/api/jobs", json={
        "kind": "backtest", "strategy": "sma_crossover",
        "source": "real", "symbol": "XLNOPE",
        "start": "2025-01-02", "end": "2025-06-30",
    })
    job = _wait(client, r.json()["job_id"])
    assert job["state"] == "error"
    assert "tradebot data pull --symbols XLNOPE" in job["error"]
    assert "--start 2025-01-02" in job["error"]
    assert "--end 2025-06-30" in job["error"]


def test_real_job_requires_a_symbol(tmp_path):
    r = _client(tmp_path).post("/api/jobs", json={
        "kind": "backtest", "strategy": "sma_crossover", "source": "real"})
    assert r.status_code == 400


def test_unknown_source_is_rejected(tmp_path):
    r = _client(tmp_path).post("/api/jobs", json={
        "kind": "backtest", "strategy": "sma_crossover", "source": "imaginary"})
    assert r.status_code == 400


def test_real_job_range_with_too_few_bars_is_an_error_not_a_verdict(tmp_path):
    df = _seed_cache(tmp_path, symbol="XLTEST", periods=150)
    client = _client(tmp_path)
    r = client.post("/api/jobs", json={
        "kind": "backtest", "strategy": "sma_crossover",
        "source": "real", "symbol": "XLTEST",
        "start": str(df.index[10].date()), "end": str(df.index[12].date()),
    })
    job = _wait(client, r.json()["job_id"])
    assert job["state"] == "error"
    assert "bars" in job["error"]


def test_synthetic_job_carries_provenance_too(tmp_path):
    client = _client(tmp_path)
    r = client.post("/api/jobs", json={
        "kind": "backtest", "strategy": "sma_crossover", "periods": 120, "seed": 9})
    job = _wait(client, r.json()["job_id"])
    assert job["state"] == "done"
    prov = job["provenance"]
    assert prov["source"] == "synthetic"
    assert prov["seed"] == 9
    assert "artificial calendar" in prov["note"]
