"""Shared pytest plumbing: the balance ledger.

Ratios like ``total_return > 0`` are fine for asserting, terrible for reading.
This plugin records the **starting and final balance** of every simulation the
suite executes — every ``Backtester.run`` and every (in-process) arena
``simulate`` — and prints the ledger after the test run, so each money test
shows its dollars:

    test_uptrend_with_always_long_is_profitable
        UP    10,000.00 -> 20,876.91  (+108.8%, 3 trades)  2023-01-02 -> 2024-05-15

Recording is automatic (the entry points are wrapped for the session); tests
need no changes. Subprocess-isolated arena runs execute in forked children,
so only thread-isolation tournaments appear. Tests that run many simulations
(leagues, seasons) are summarised as a range instead of listed row by row.
"""

from __future__ import annotations

import pytest

#: nodeid -> list of {symbols, start, final, trades} in execution order.
_LEDGER: dict[str, list[dict]] = {}
#: nodeid of the currently running test ("" outside any test).
_CURRENT: list[str] = [""]


@pytest.fixture(autouse=True)
def _current_test(request):
    _CURRENT[0] = request.node.nodeid
    yield
    _CURRENT[0] = ""


def _record(symbols, result) -> None:
    node = _CURRENT[0]
    if not node:
        return
    curve = result.equity_curve
    _LEDGER.setdefault(node, []).append({
        "symbols": ",".join(symbols),
        "start": float(result.initial_cash),
        "final": float(result.final_equity),
        "trades": result.num_trades,
        "first": str(curve.index[0])[:10] if len(curve) else "?",
        "last": str(curve.index[-1])[:10] if len(curve) else "?",
    })


@pytest.fixture(autouse=True, scope="session")
def _balance_ledger():
    from tradebot import backtest as backtest_mod
    from tradebot.arena import runner as runner_mod
    from tradebot.arena import simulation as simulation_mod

    orig_run = backtest_mod.Backtester.run
    orig_simulate = simulation_mod.simulate

    def run_wrapper(self, data, symbol="ASSET"):
        result = orig_run(self, data, symbol)
        _record(list(data) if isinstance(data, dict) else [symbol], result)
        return result

    def simulate_wrapper(policy, frames, *args, **kwargs):
        result = orig_simulate(policy, frames, *args, **kwargs)
        _record(list(frames), result)
        return result

    backtest_mod.Backtester.run = run_wrapper
    simulation_mod.simulate = simulate_wrapper
    runner_mod.simulate = simulate_wrapper   # runner binds the name at import
    yield
    backtest_mod.Backtester.run = orig_run
    simulation_mod.simulate = orig_simulate
    runner_mod.simulate = orig_simulate


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    if not _LEDGER:
        return
    tr = terminalreporter
    tr.write_sep("-", "simulated balances (start -> final)")
    for node, runs in _LEDGER.items():
        tr.line(node)
        if len(runs) > 4:
            finals = sorted(r["final"] for r in runs)
            first = min(r["first"] for r in runs)
            last = max(r["last"] for r in runs)
            tr.line(f"    {len(runs)} sims from {runs[0]['start']:,.2f} -> "
                    f"[{finals[0]:,.2f} ... {finals[-1]:,.2f}]   {first} -> {last}")
            continue
        for r in runs:
            pct = r["final"] / r["start"] - 1.0 if r["start"] else 0.0
            symbols = r["symbols"] if len(r["symbols"]) <= 20 else r["symbols"][:17] + "..."
            tr.line(f"    {symbols:<20} {r['start']:>12,.2f} -> {r['final']:>12,.2f}"
                    f"   ({pct:+.1%}, {r['trades']} trades)   {r['first']} -> {r['last']}")
