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
#:
#: Balanced by construction so no single mechanism can sweep a strict majority:
#: selection is rewarded by bull_dispersion and chop_dispersion and punished by
#: momentum_crash; defense is rewarded by crash_haven and vol_spike_down and
#: punished by crash_nohaven and vol_spike_up.
XS_SCENARIOS = [
    "xs_bull_dispersion", "xs_chop_dispersion", "xs_momentum_crash",
    "xs_crash_haven", "xs_crash_nohaven",
    "xs_vol_spike_up", "xs_vol_spike_down",
]

#: (rewards mechanism, punishes mechanism) pairs. Each must differ by exactly
#: one parameter so weakening the punishing half is a visible one-line diff.
MIRROR_PAIRS = [("xs_crash_haven", "xs_crash_nohaven"),
                ("xs_vol_spike_down", "xs_vol_spike_up")]


#: Real-data gauntlet. Needs one `tradebot data pull`; the cache is gitignored,
#: so these skip rather than fail where it is absent (CI, a fresh clone).
REAL_XS_SCENARIOS = ["real_xs_2021", "real_xs_2022", "real_xs_2023",
                     "real_xs_2024_2025h1"]


def _load(name: str) -> Scenario:
    return Scenario.from_yaml(SCENARIOS / f"{name}.yaml")


def _load_real(name: str) -> Scenario:
    scenario = _load(name)
    try:
        scenario.build_frames()
    except Exception as exc:      # no cached bars in this checkout
        pytest.skip(f"{name} needs cached bars (`tradebot data pull`): {exc}")
    return scenario


@pytest.mark.parametrize("name", REAL_XS_SCENARIOS)
def test_real_scenario_is_not_degenerate_for_selection(name):
    """The same check that fails on the old SPY/QQQ/IWM pack at 0%.

    That pack is why this test exists: `top_k=2` over two or three correlated
    equity-beta ETFs selects everything every bar, so months of verdicts were
    produced by a gauntlet that could not see the mechanism it claimed to test.
    """
    frames = _load_real(name).build_frames()
    assert len(frames) > 2, "pool too small for top-2 selection to mean anything"

    momentum = MomentumSelector(lookback=60, skip=5, top_k=2)
    low_vol = LowVolatilitySelector(window=30, top_k=2)
    warmup = max(momentum.required_history, low_vol.required_history)
    mom = momentum.membership(frames).iloc[warmup:]
    lov = low_vol.membership(frames).iloc[warmup:]

    assert int((mom != mom.shift(1)).any(axis=1).sum()) > 1, "membership never changes"
    disagree = float((mom != lov).any(axis=1).mean())
    assert disagree >= 0.20, (
        f"{name}: two selectors agree on {1 - disagree:.0%} of live bars")


def test_the_real_haven_is_not_unconditionally_a_haven():
    """TLT must FAIL as a haven in 2022 and work elsewhere.

    A pool whose haven always works is flattery: a candidate could win by
    holding bonds rather than by timing anything. 2022 is in the pack precisely
    because rates rose and bonds fell alongside equities.
    """
    def total(name, symbol):
        frames = _load_real(name).build_frames()
        close = frames[symbol]["close"]
        return close.iloc[-1] / close.iloc[0] - 1.0

    assert total("real_xs_2022", "TLT") < -0.15, "the haven did not fail in 2022"
    assert total("real_xs_2023", "GLD") > 0.0, "no haven works anywhere in the pack"


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


@pytest.mark.parametrize("rewards,punishes", MIRROR_PAIRS)
def test_mirror_pair_differs_by_exactly_one_parameter(rewards, punishes):
    """Mirror halves must be one parameter apart.

    Mirror pairs are the library's defence against only ever rewarding the
    mechanisms it happens to contain. If a pair can drift apart on other
    parameters, the "punishing" half can be quietly weakened until a favoured
    candidate passes — and that edit would be invisible in review.
    """
    a_sc, b_sc = _load(rewards), _load(punishes)

    assert a_sc.seed == b_sc.seed, "mirror halves must share a seed"
    assert a_sc.symbols == b_sc.symbols
    assert a_sc.factor_symbols == b_sc.factor_symbols
    assert len(a_sc.regimes) == len(b_sc.regimes)

    diffs = set()
    for x, y in zip(a_sc.regimes, b_sc.regimes):
        for key in set(x) | set(y):
            if x.get(key, 0.0) != y.get(key, 0.0):
                diffs.add(key)
    assert len(diffs) == 1, f"{rewards} vs {punishes} differ on {sorted(diffs)}"


def test_vol_spike_mirror_is_symmetric_in_magnitude():
    """The vol-spike pair must differ only in the SIGN of the spike drift.

    An asymmetric pair would smuggle in a second difference: a shallow up-move
    against a deep down-move rewards defence twice over.
    """
    up, down = _load("xs_vol_spike_up"), _load("xs_vol_spike_down")
    up_drift = up.regimes[1]["drift"]
    down_drift = down.regimes[1]["drift"]
    assert up_drift == pytest.approx(-down_drift)
    assert up.regimes[1]["volatility"] == down.regimes[1]["volatility"]


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


def _canary_scores(scenario):
    """Run the canaries plus two real books over one scenario."""
    from tradebot.arena.tournament import run_tournament

    algos = Path(__file__).resolve().parents[1] / "algos"
    paths = [str(algos / "canaries"), str(algos / "xs_momentum.py"),
             str(algos / "buy_and_hold.py")]
    outcome = run_tournament(paths, scenario, metric="total_return",
                             isolation="thread", time_budget_s=120)
    return {e.name: e.total_return for e in outcome.leaderboard.entries if e.ok}


@pytest.mark.parametrize("name", ["xs_bull_dispersion", "xs_chop_dispersion"])
def test_an_oracle_can_win_so_the_scenario_contains_signal(name):
    """The sharpest single test of whether a scenario is worth running.

    `oracle_topk` selects on future returns. If something that can see ahead
    cannot beat the field by a wide margin, there is nothing in the scenario to
    exploit and every verdict on it — pass or fail — is noise.

    Candidate-agnostic by construction: it asks whether the scenario can
    measure skill, never whether a favoured contestant won, so it cannot be
    used to tune a scenario toward a result.
    """
    scores = _canary_scores(_load(name))
    for who in ("oracle_topk", "random_topk", "always_haven"):
        assert who in scores, f"{who} did not complete on {name}"

    others = max(v for k, v in scores.items() if k != "oracle_topk")
    assert scores["oracle_topk"] > others + 0.50, (
        f"{name}: oracle {scores['oracle_topk']:.1%} vs best-other {others:.1%} — "
        "no exploitable signal, so no verdict from this scenario means anything")


def test_hiding_is_not_free_when_the_market_rises():
    """`always_haven` must lose in a rising market, in expectation.

    Deliberately scoped to the rising scenario. In flat or falling markets a
    low-beta asset with slight positive carry is *legitimately* competitive —
    measured across seeds the haven often beats random selection in
    `xs_chop_dispersion`. That is realistic behaviour, not a flattering
    scenario, and asserting otherwise would be forcing the data to match a
    slogan.
    """
    import dataclasses

    base = _load("xs_bull_dispersion")
    haven_loses = 0
    for k in range(3):
        scenario = base if k == 0 else dataclasses.replace(base, seed=base.seed + k)
        scores = _canary_scores(scenario)
        haven_loses += scores["always_haven"] < scores["buy_and_hold"]
    assert haven_loses >= 2, (
        "sitting in the haven kept up with holding everything in a rising "
        "market — defence is free here and the scenario flatters defensive books")


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
