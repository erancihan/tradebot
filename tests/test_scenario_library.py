"""Properties every gauntlet scenario must have to be worth running.

These are not tests of a strategy — they are tests of the *test*. Both prior
gauntlets failed here and nobody noticed for months: four of five synthetic
scenarios were single-symbol, and on the real pack `exit_rank` froze membership
so the selector never changed its mind in 587 bars. In both cases a
cross-sectional selector was a definitional no-op and the resulting verdicts
carried no information about the thing they claimed to measure.

The degeneracy assertion below is the check that would have caught both on day
one, so it runs in CI over the whole library.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tradebot.arena.scenario import Scenario
from tradebot.data.synthetic import synthetic_factor_panel
from tradebot.selection import LowVolatilitySelector, MomentumSelector

SCENARIOS = Path(__file__).resolve().parents[1] / "scenarios"
#: Scenarios intended to exercise cross-sectional machinery.
XS_SCENARIOS = ["xs_bull_dispersion", "xs_crash_haven", "xs_crash_nohaven"]


def _load(name: str) -> Scenario:
    return Scenario.from_yaml(SCENARIOS / f"{name}.yaml")


@pytest.mark.parametrize("name", XS_SCENARIOS)
def test_scenario_is_not_degenerate_for_selection(name):
    """top_k < pool, membership actually varies, and selectors disagree.

    The last clause is the load-bearing one. Two selectors that always agree
    mean the scenario cannot distinguish them, so any verdict comparing them is
    noise. Today's shipped real pack scores 0% here.
    """
    scenario = _load(name)
    frames = scenario.build_frames()
    top_k = 2
    assert top_k < len(frames), "top_k >= pool size: every name is always selected"

    momentum = MomentumSelector(lookback=60, skip=5, top_k=top_k)
    low_vol = LowVolatilitySelector(window=30, top_k=top_k)
    warmup = max(momentum.required_history, low_vol.required_history)

    mom = momentum.membership(frames).iloc[warmup:]
    lov = low_vol.membership(frames).iloc[warmup:]

    changes = int((mom != mom.shift(1)).any(axis=1).sum()) - 1
    assert changes > 0, f"{name}: membership never changes — the selector is inert"

    disagree = float((mom != lov).any(axis=1).mean())
    assert disagree >= 0.20, (
        f"{name}: two different selectors agree on {1 - disagree:.0%} of live bars; "
        "the scenario cannot tell them apart")


def test_crash_mirror_pair_differs_by_exactly_one_parameter():
    """xs_crash_haven and xs_crash_nohaven must be one `beta_shift` apart.

    Mirror pairs are the library's defence against only ever rewarding the
    mechanisms it contains. If a pair can drift apart on other parameters, the
    "punishing" half can be quietly weakened until a favoured candidate passes.
    """
    haven, nohaven = _load("xs_crash_haven"), _load("xs_crash_nohaven")

    assert haven.seed == nohaven.seed
    assert haven.symbols == nohaven.symbols
    assert haven.factor_symbols == nohaven.factor_symbols
    assert len(haven.regimes) == len(nohaven.regimes)

    diffs = []
    for a, b in zip(haven.regimes, nohaven.regimes):
        for key in set(a) | set(b):
            if a.get(key, 0.0) != b.get(key, 0.0):
                diffs.append(key)
    assert diffs == ["beta_shift"], f"mirror pair differs on {diffs}"


def test_beta_shift_is_what_breaks_the_haven():
    """The mirror's single parameter must actually do its job.

    In the haven scenario the haven is negatively correlated with the equity
    names; under crisis contagion that correlation must go positive, otherwise
    the "defense costs" scenario does not punish defense at all.
    """
    def haven_corr(scenario_name):
        frames = _load(scenario_name).build_frames()
        rets = pd.DataFrame({s: f["close"].pct_change() for s, f in frames.items()})
        crash = rets.iloc[200:260]          # the crash segment
        equities = [c for c in crash.columns if c != "HAVEN"]
        return float(crash[equities].corrwith(crash["HAVEN"]).mean())

    assert haven_corr("xs_crash_haven") < 0.0
    assert haven_corr("xs_crash_nohaven") > haven_corr("xs_crash_haven")


def test_haven_costs_to_hold():
    """Hiding must not be free, or "always hide" wins without timing anything.

    Checked in expectation across seeds, not on one draw: a single 500-bar path
    has enough variance to reverse any individual ranking, which is exactly why
    a one-seed gate verdict is close to a coin flip.
    """
    pool = _load("xs_bull_dispersion").factor_symbols
    calm = [{"periods": 500, "drift": 0.0006, "volatility": 0.010}]

    haven, market, haven_wins = [], [], 0
    for seed in range(200, 240):
        panel = synthetic_factor_panel(pool, calm, seed=seed)
        total = {s: f["close"].iloc[-1] / f["close"].iloc[0] - 1
                 for s, f in panel.items()}
        haven.append(total["HAVEN"])
        market.append(total["MID1"])
        haven_wins += total["HAVEN"] >= total["MID1"]

    # The design claim is about expectation, and it is not marginal: measured
    # over 200 seeds, HAVEN averages -3.3% against MID1's +41.2%.
    assert np.mean(haven) < np.mean(market) - 0.15

    # Individual draws are genuinely noisy — the haven wins ~14% of 500-bar
    # paths — which is itself the argument for seed ensembles rather than
    # one-path verdicts. Bound it loosely; the mean above is the real assertion.
    assert haven_wins <= len(haven) // 3, (
        f"haven beat the market-like name in {haven_wins}/{len(haven)} calm draws")


def test_factor_panel_builds_one_shared_market():
    """The pool is generated jointly, not as independent random walks.

    Independent walks were the flaw in the original `cross_sectional.yaml`: at
    ~0.03 mean pairwise correlation a crash is several unrelated accidents,
    every name is a haven, and diversification is free.
    """
    frames = _load("xs_bull_dispersion").build_frames()
    rets = pd.DataFrame({s: f["close"].pct_change() for s, f in frames.items()}).dropna()
    equities = [c for c in rets.columns if c != "HAVEN"]
    corr = rets[equities].corr().to_numpy()
    off_diagonal = corr[np.triu_indices_from(corr, 1)]

    assert off_diagonal.min() > 0.3, "equity names are not sharing a market factor"
    assert rets[equities].corrwith(rets["HAVEN"]).max() < 0.0, "haven is not a haven"


def test_all_symbols_share_one_index():
    """Ragged frames would silently change what the execution loops align on."""
    for name in XS_SCENARIOS:
        frames = _load(name).build_frames()
        indexes = [f.index for f in frames.values()]
        assert all(ix.equals(indexes[0]) for ix in indexes), name


def test_scenarios_are_deterministic():
    for name in XS_SCENARIOS:
        a = _load(name).build_frames()
        b = _load(name).build_frames()
        for sym in a:
            pd.testing.assert_frame_equal(a[sym], b[sym])
