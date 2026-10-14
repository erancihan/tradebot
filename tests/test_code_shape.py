"""Shape limits for the codebase: short functions, small package modules.

Long functions and sprawling modules are where this project's worst bugs hid
(the sizing look-ahead lived in a 100-line loop body), so the limits are
enforced mechanically rather than by review.
"""

from __future__ import annotations

import ast
from pathlib import Path

MAX_FUNCTION_LINES = 60
MAX_MODULE_LINES = 200

ROOT = Path(__file__).resolve().parent.parent

# Tolerated while the rest of the package is split up in parallel. Keys are
# `path` for an oversized module and `path::function` for an oversized
# function. An entry that no longer offends fails the suite, so this list can
# only shrink — delete the line in the same change that fixes the offender.
KNOWN_OFFENDERS: set[str] = {
    "tradebot/arena/gate.py",  # split in progress
    "tradebot/arena/gate.py::evaluate_gate",  # split in progress
    "tradebot/arena/runner.py",  # split in progress
    "tradebot/arena/season.py",  # split in progress
    "tradebot/arena/simulation.py::simulate",  # split in progress
    "tradebot/arena/store.py",  # split in progress
    "tradebot/backtest.py",  # split in progress
    "tradebot/backtest.py::run",  # split in progress
    "tradebot/broker/dryrun.py",  # split in progress
    "tradebot/consortium.py",  # split in progress
    "tradebot/data/cache.py",  # split in progress
    "tradebot/data/synthetic.py",  # split in progress
    "tradebot/data/synthetic.py::synthetic_factor_panel",  # split in progress
    "tradebot/engine.py",  # split in progress
    "tradebot/engine.py::rebalance",  # split in progress
    "tradebot/selection.py",  # split in progress
    "tradebot/storage.py",  # split in progress
    "tradebot/universe.py",  # split in progress
    "tradebot/walkforward.py::walk_forward",  # split in progress
}


def _python_files(*roots: str) -> list[Path]:
    return sorted(p for r in roots for p in (ROOT / r).rglob("*.py"))


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _long_functions() -> dict[str, str]:
    """`path::name` -> the human-readable report line, for every offender."""
    found: dict[str, str] = {}
    for path in _python_files("tradebot", "tests"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            length = node.end_lineno - node.lineno + 1
            if length > MAX_FUNCTION_LINES:
                found[f"{_rel(path)}::{node.name}"] = (
                    f"{_rel(path)}:{node.lineno} {node.name} ({length} lines)")
    return found


def _long_modules() -> dict[str, str]:
    found: dict[str, str] = {}
    for path in _python_files("tradebot"):
        length = len(path.read_text().splitlines())
        if length > MAX_MODULE_LINES:
            found[_rel(path)] = f"{_rel(path)} ({length} lines)"
    return found


def _check(found: dict[str, str], known: set[str], what: str) -> None:
    new = sorted(line for key, line in found.items() if key not in known)
    stale = sorted(known - set(found))
    problems = []
    if new:
        problems.append(f"{what} over the limit:\n  " + "\n  ".join(new))
    if stale:
        problems.append("KNOWN_OFFENDERS entries that no longer offend "
                        "(remove them):\n  " + "\n  ".join(stale))
    assert not problems, "\n".join(problems)


def test_no_function_exceeds_limit() -> None:
    known = {k for k in KNOWN_OFFENDERS if "::" in k}
    _check(_long_functions(), known, f"functions (max {MAX_FUNCTION_LINES} lines)")


def test_no_package_module_exceeds_limit() -> None:
    known = {k for k in KNOWN_OFFENDERS if "::" not in k}
    _check(_long_modules(), known, f"modules (max {MAX_MODULE_LINES} lines)")


def test_known_offenders_never_cover_the_cli() -> None:
    # The CLI was split to these limits outright; it gets no grace period.
    assert not {k for k in KNOWN_OFFENDERS if k.startswith("tradebot/cli/")}
