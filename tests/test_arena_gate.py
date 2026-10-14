"""The promotion pass gate: candidate vs baseline over a scenario gauntlet."""

import numpy as np
import pandas as pd
import pytest

from tradebot.arena.contestant import Contestant
from tradebot.arena.gate import evaluate_gate
from tradebot.arena.result import ERROR, OK, ContestantResult, Leaderboard
from tradebot.arena.tournament import TournamentOutcome
from tradebot.backtest import BacktestResult
from tradebot.cli import main


def _bt(equity: list[float]) -> BacktestResult:
    curve = pd.Series(equity,
                      index=pd.date_range("2023-01-02", periods=len(equity),
                                          freq="1D", tz="UTC"), dtype=float)
    return BacktestResult(equity_curve=curve, trades=[], initial_cash=equity[0])


def _entry(name, equity, status=OK, family=None):
    c = Contestant(name=name, factory=lambda: None, kind="event",
                   family=family or name)
    if status != OK:
        return ContestantResult(c, status=status, error="boom")
    return ContestantResult(c, status=OK, score=0.0, result=_bt(equity))


def _outcome(*entries):
    return TournamentOutcome(leaderboard=Leaderboard.build("worst_fold", list(entries)),
                             load_errors=[])


STEADY_UP = list(100 * 1.004 ** np.arange(41))       # beats flat everywhere
FLAT = [100.0] * 41
CRASHY = (list(np.linspace(100, 150, 21))
          + list(np.linspace(150, 55, 11))[1:]       # -63% drawdown fold
          + list(np.linspace(55, 60, 11))[1:])


def test_gate_passes_a_dominating_candidate():
    outcomes = [
        ("bull", _outcome(_entry("cand", STEADY_UP), _entry("base", FLAT))),
        ("chop", _outcome(_entry("cand", STEADY_UP), _entry("base", FLAT))),
        ("crash", _outcome(_entry("cand", STEADY_UP), _entry("base", FLAT))),
    ]
    report = evaluate_gate("cand", "base", outcomes)
    assert report.passed
    assert all(c.passed for c in report.checks)
    text = report.table()
    assert "VERDICT: PASS" in text and "bull" in text


def test_gate_fails_on_error_drawdown_or_underperformance():
    # An error in any scenario fails the completeness check.
    with_err = [
        ("bull", _outcome(_entry("cand", STEADY_UP), _entry("base", FLAT))),
        ("chop", _outcome(_entry("cand", None, status=ERROR), _entry("base", FLAT))),
    ]
    r1 = evaluate_gate("cand", "base", with_err)
    assert not r1.passed
    assert "ERROR" in r1.table()

    # A deep drawdown fails the bound even when returns look fine elsewhere.
    crashy = [("bull", _outcome(_entry("cand", CRASHY), _entry("base", FLAT)))]
    r2 = evaluate_gate("cand", "base", crashy, max_drawdown_limit=0.35)
    dd_check = [c for c in r2.checks if "drawdown" in c.label][0]
    assert not dd_check.passed and not r2.passed

    # Losing to the baseline on mean return fails.
    losing = [("bull", _outcome(_entry("cand", FLAT), _entry("base", STEADY_UP)))]
    r3 = evaluate_gate("cand", "base", losing)
    assert not r3.passed


def test_gate_requires_both_names_present():
    outcomes = [("bull", _outcome(_entry("cand", STEADY_UP)))]
    with pytest.raises(ValueError, match="baseline"):
        evaluate_gate("cand", "missing", outcomes)
    with pytest.raises(ValueError, match="candidate"):
        evaluate_gate("missing", "cand", outcomes)
    with pytest.raises(ValueError, match="scenario"):
        evaluate_gate("cand", "base", [])


def _write_scenario(tmp_path, name, drift, vol=0.005, periods=160, seed=3):
    p = tmp_path / f"{name}.yaml"
    p.write_text(
        f"name: {name}\nsource: synthetic\nsymbols: [DEMO]\n"
        f"periods: {periods}\nseed: {seed}\ndrift: {drift}\nvolatility: {vol}\n"
        "risk: {max_position_pct: 0.95, max_daily_loss_pct: 1.0}\n"
    )
    return str(p)


def _write_algos(tmp_path):
    p = tmp_path / "field.py"
    p.write_text(
        "from tradebot.arena import register, Algo, Action\n"
        "from tradebot.strategies import BuyAndHold\n"
        "@register(name='holder')\n"
        "class Holder(BuyAndHold):\n"
        "    pass\n"
        "@register(name='sitter')\n"
        "class Sitter(Algo):\n"
        "    def on_bar(self, bar, ctx): return Action.flat()\n"
    )
    return str(p)


def test_cli_gate_pass_and_fail_exit_codes(tmp_path, capsys):
    algos = _write_algos(tmp_path)
    up1 = _write_scenario(tmp_path, "up1", drift=0.002, seed=3)
    up2 = _write_scenario(tmp_path, "up2", drift=0.0015, seed=4)
    db = str(tmp_path / "arena.db")

    # The always-long candidate beats the always-flat baseline on an uptrend.
    rc = main(["arena", "gate", "--algos", algos, "--candidate", "holder",
               "--baseline", "sitter", "--scenarios", up1, up2,
               "--isolation", "thread", "--db", db])
    out = capsys.readouterr().out
    assert rc == 0
    assert "VERDICT: PASS" in out
    assert "attempt(s) on record" in out          # journal count surfaced

    # Swap roles: the sitter cannot beat the holder -> FAIL, exit code 1.
    rc = main(["arena", "gate", "--algos", algos, "--candidate", "sitter",
               "--baseline", "holder", "--scenarios", up1, up2,
               "--isolation", "thread", "--db", db])
    out = capsys.readouterr().out
    assert rc == 1
    assert "VERDICT: FAIL" in out


def test_cli_gate_journals_only_the_candidate_family(tmp_path, capsys):
    """A gate run charges attempts to the idea under development — nobody else.

    The gate runs the whole field against every gauntlet scenario just to obtain
    a baseline. Journaling all of them charged +1 attempt per scenario to every
    family, so a never-iterated baseline accumulated the same attempt count as
    the candidate and the multiple-testing statistic measured gate invocations
    rather than iterations of an idea.
    """
    algos = _write_algos(tmp_path)
    up = _write_scenario(tmp_path, "up", drift=0.002)
    db = str(tmp_path / "arena.db")
    main(["arena", "gate", "--algos", algos, "--candidate", "holder",
          "--baseline", "sitter", "--scenarios", up,
          "--isolation", "thread", "--db", db])
    capsys.readouterr()
    assert main(["arena", "journal", "--db", db]) == 0
    out = capsys.readouterr().out
    assert "holder" in out
    assert "sitter" not in out          # the baseline is a reference, not an attempt


def test_the_drawdown_check_shows_the_frame_it_is_judging_in():
    """M5: three criteria are relative, the absolute one needs its frame shown.

    When the baseline itself breaches the bound, an absolute limit is partly
    measuring the *scenario* rather than the candidate. The check has to say so
    at the point of use, or a FAIL reads as "too risky" when it sometimes means
    "this regime is". The criterion is deliberately unchanged — only what it
    reports.
    """
    # Candidate crashes hard; baseline crashes HARDER.
    worse = (list(np.linspace(100, 150, 21))
             + list(np.linspace(150, 30, 11))[1:]
             + list(np.linspace(30, 35, 11))[1:])
    both_deep = [("crash", _outcome(_entry("cand", CRASHY), _entry("base", worse)))]

    report = evaluate_gate("cand", "base", both_deep, max_drawdown_limit=0.35)
    dd = [c for c in report.checks if "drawdown" in c.label][0]

    assert not dd.passed                      # the criterion still bites
    assert "baseline" in dd.detail            # ...but the frame is visible
    assert "measuring the regime" in dd.detail


def test_the_regime_note_stays_quiet_when_the_baseline_is_inside_the_bound():
    """No note when the comparison is not confounded — signal, not decoration."""
    shallow = [("bull", _outcome(_entry("cand", CRASHY), _entry("base", FLAT)))]

    report = evaluate_gate("cand", "base", shallow, max_drawdown_limit=0.35)
    dd = [c for c in report.checks if "drawdown" in c.label][0]

    assert not dd.passed
    assert "baseline" in dd.detail
    assert "measuring the regime" not in dd.detail


def test_the_relative_bound_only_applies_where_the_absolute_one_is_confounded():
    """M5: the relative frame is for regimes where the absolute bound stops
    measuring the candidate — not a second bound applied everywhere.

    Unscoped, it is unsatisfiable: an all-cash baseline takes zero drawdown, so
    no long-only candidate could ever match it. Same trivial optimum that makes
    `worst_fold` degenerate on its own.
    """
    calm_base = list(np.linspace(100, 97, 41))         # -3%: nowhere near -35%
    sinker = list(np.linspace(100, 75, 41))            # -25%: deeper, still legal

    report = evaluate_gate("cand", "base",
                           [("chop", _outcome(_entry("cand", sinker),
                                              _entry("base", calm_base)))],
                           max_drawdown_limit=0.35)
    labels = [c.label for c in report.checks]

    # The candidate is 22pp deeper than the baseline and the check does not fire,
    # because the absolute bound is the meaningful test in a calm regime.
    assert not any("confounded" in x for x in labels)
    assert any("not applicable" in n for n in report.notes)

    # Now a regime where the baseline itself blows through the bound: the
    # relative comparison is the one carrying information, and it bites.
    wrecked_base = (list(np.linspace(100, 120, 21))
                    + list(np.linspace(120, 40, 20)))          # ~-67%
    worse_cand = (list(np.linspace(100, 120, 21))
                  + list(np.linspace(120, 25, 20)))            # ~-79%, worse still
    report = evaluate_gate("cand", "base",
                           [("crash", _outcome(_entry("cand", worse_cand),
                                               _entry("base", wrecked_base)))],
                           max_drawdown_limit=0.35)
    relative = [c for c in report.checks if "confounded" in c.label][0]
    assert not relative.passed
    assert not report.passed


def test_adding_the_relative_bound_can_only_make_the_gate_stricter():
    """The property that made this admissible: it converts no recorded FAIL.

    A required check can only turn PASS into FAIL. If this ever rescues a
    candidate, the criterion has been rewritten rather than added to.
    """
    deep = (list(np.linspace(100, 150, 21))
            + list(np.linspace(150, 55, 11))[1:]
            + list(np.linspace(55, 60, 11))[1:])          # breaches -35%
    worse_base = (list(np.linspace(100, 150, 21))
                  + list(np.linspace(150, 30, 11))[1:]
                  + list(np.linspace(30, 35, 11))[1:])    # baseline is deeper still

    report = evaluate_gate("cand", "base",
                           [("crash", _outcome(_entry("cand", deep),
                                               _entry("base", worse_base)))],
                           max_drawdown_limit=0.35)
    relative = [c for c in report.checks if "confounded" in c.label][0]
    absolute = [c for c in report.checks if "never worse than" in c.label][0]

    # The candidate beats the baseline on drawdown and STILL fails the gate:
    # winning the relative check cannot rescue an absolute breach.
    assert relative.passed
    assert not absolute.passed
    assert not report.passed
