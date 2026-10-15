"""Compare strategies on the What-if page: one plan, every rule, ranked."""

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from tradebot.web.guard import POST_HEADERS  # noqa: E402
from tradebot.web.services.jobs.whatif_compare import TOP_CURVES  # noqa: E402
from tests.test_web_whatif import _client, _seed_cache, _wait  # noqa: E402

PLAN = {"symbols": ["DEMO", "TOY", "ZED"], "source": "synthetic",
        "start": "2021-01-04", "end": "2022-12-30",
        "initial_cash": 10000, "monthly_contribution": 200, "strategy": "sma_crossover"}


def _compare(client, body):
    return client.post("/api/whatif/compare", headers=POST_HEADERS, json=body)


def test_compare_job_ranks_every_runnable_strategy_on_synthetic_data(tmp_path):
    from tradebot.strategies import STRATEGIES

    client = _client(tmp_path)
    r = _compare(client, PLAN)
    assert r.status_code == 200
    job = _wait(client, r.json()["job_id"], timeout=60)
    assert job["state"] == "done", job.get("error")
    assert job["kind"] == "whatif_compare"
    out = job["compare"]
    names = [row["name"] for row in out["rows"]]
    skipped = {s["name"] for s in out["skipped"]}
    assert skipped == {"follow_leader", "ensemble_vote"}
    assert set(names) == set(STRATEGIES) - skipped
    values = [row["final_value"] for row in out["rows"]]
    assert values == sorted(values, reverse=True)
    assert out["benchmark"]["benchmark"] is True
    assert out["plan_strategy"] == "sma_crossover"
    assert out["errors"] == []
    assert job["provenance"]["source"] == "synthetic"
    assert job["provenance"]["symbol"] == "DEMO,TOY,ZED"


def test_compare_curves_are_the_top_five_plus_the_benchmark(tmp_path):
    client = _client(tmp_path)
    job = _wait(client, _compare(client, PLAN).json()["job_id"], timeout=60)
    out = job["compare"]
    top = [row["name"] for row in out["rows"][:TOP_CURVES]]
    assert TOP_CURVES == 5
    assert set(out["curves"]) == set(top) | {"benchmark"}
    for curve in out["curves"].values():
        assert len(curve["equity"]) == job["provenance"]["bars"]
        assert len(curve["index"]) == len(curve["equity"])


def test_compare_runs_from_the_cache(tmp_path):
    _seed_cache(tmp_path)
    client = _client(tmp_path)
    r = _compare(client, {"symbols": ["aaa", "BBB"], "start": "2022-02-01",
                          "initial_cash": 5000, "monthly_contribution": 100})
    job = _wait(client, r.json()["job_id"], timeout=60)
    assert job["state"] == "done", job.get("error")
    assert job["provenance"]["source"] == "real"
    assert job["compare"]["plan_strategy"] == "buy_and_hold"


@pytest.mark.parametrize("body", [
    {"symbols": [], "source": "synthetic", "initial_cash": 1000},
    {"symbols": [f"S{i}" for i in range(13)], "source": "synthetic", "initial_cash": 1000},
    {"symbols": ["SPY"], "source": "synthetic", "initial_cash": 0},
    {"symbols": ["SPY"], "source": "synthetic", "initial_cash": 100,
     "monthly_contribution": -5},
    {"symbols": ["SPY"], "source": "web", "initial_cash": 100},
    {"symbols": ["../etc"], "source": "real", "initial_cash": 100},
])
def test_compare_validates_the_plan_like_a_single_run(tmp_path, body):
    assert _compare(_client(tmp_path), body).status_code == 400


def test_compare_needs_the_same_origin_header(tmp_path):
    r = _client(tmp_path).post("/api/whatif/compare", json=PLAN)
    assert r.status_code == 403


def test_whatif_page_offers_compare_strategies(tmp_path):
    text = _client(tmp_path).get("/whatif").text
    assert "Compare strategies" in text
    assert "data-compare-card" in text


def test_a_tuned_plan_comes_back_as_its_own_flagged_row(tmp_path):
    client = _client(tmp_path)
    body = {**PLAN, "params": {"fast": 5, "slow": 12}}
    job = _wait(client, _compare(client, body).json()["job_id"], timeout=60)
    assert job["state"] == "done", job.get("error")
    flagged = [r["name"] for r in job["compare"]["rows"] if r.get("plan")]
    assert flagged == ["sma_crossover (your settings)"]
    assert "sma_crossover" in [r["name"] for r in job["compare"]["rows"]]
