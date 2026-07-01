"""A discovered competitor: metadata plus a factory for fresh instances."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass
class Contestant:
    """One entry in a tournament.

    ``factory`` is called with no arguments to build a fresh strategy/algo
    instance per round (so stateful event algos never leak state between runs).
    ``kind`` is "vectorized" (a Strategy) or "event" (an Algo).
    """

    name: str
    factory: Callable[[], object]
    kind: str
    author: str = ""
    tags: tuple[str, ...] = ()
    source: str = ""  # set by the loader to the file the contestant came from

    def make(self) -> object:
        return self.factory()
