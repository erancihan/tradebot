"""Write throwaway contestant files for the process-isolation tests.

A process-isolated contestant is imported and built inside a fresh, hardened
interpreter, so it must live in a file: a class defined in a test function
cannot cross into a new interpreter. These helpers keep that boilerplate out
of the tests.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from tradebot.arena.contestant import Contestant
from tradebot.arena.scoring import get_scorer
from tradebot.arena.simulation import SimConfig
from tradebot.data.synthetic import synthetic_ohlcv
from tradebot.risk import RiskConfig, RiskManager

_TEMPLATE = '''\
import os
from tradebot.arena import Action, Algo, register
{prelude}

@register(name={name!r}, author="t")
class Contestant_(Algo):
    def on_bar(self, bar, ctx):
{body}
        return Action.flat()
'''


def algo_file(directory: Path, body: str = "pass", *, prelude: str = "",
              name: str = "x") -> Path:
    """A one-contestant file whose ``on_bar`` runs ``body`` then goes flat."""
    path = Path(directory) / f"{name}.py"
    path.write_text(_TEMPLATE.format(
        prelude=textwrap.dedent(prelude), name=name,
        body=textwrap.indent(textwrap.dedent(body), " " * 8)))
    return path


def file_contestant(path: Path, name: str = "x") -> Contestant:
    """A contestant known only by file and name, as the parent sees it."""
    return Contestant(name=name, factory=_unbuilt, kind="event", source=str(path))


def _unbuilt():
    raise AssertionError("a process-isolated contestant is built in the child")


def run_file(runner, path: Path, name: str = "x", scorer=None, periods: int = 40):
    df = synthetic_ohlcv(periods=periods, seed=1)
    return runner.run(file_contestant(path, name), {"DEMO": df},
                      RiskManager(RiskConfig()), SimConfig(),
                      scorer or get_scorer("total_return"))
