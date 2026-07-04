"""The ``@register`` decorator and the module-level contestant registry.

Authors annotate their class with ``@register(...)``; importing the module (the
loader does this) appends a :class:`Contestant` to ``_REGISTRY``. The loader
snapshots the registry around each file import to attribute contestants to their
source file.
"""

from __future__ import annotations

from .contestant import Contestant
from .interfaces import Algo

# Populated as a side effect of importing modules that use @register.
_REGISTRY: list[Contestant] = []


def clear_registry() -> None:
    _REGISTRY.clear()


def registered() -> list[Contestant]:
    return list(_REGISTRY)


def register(name: str | None = None, *, author: str = "", tags=(), family: str | None = None):
    """Register a contestant class (an ``Algo`` or a ``Strategy`` subclass).

    ``family`` groups variants of one idea (e.g. ``donchian_20_10`` and
    ``donchian_55_20`` both under ``family="donchian"``) so the experiment
    journal counts attempts against the family, not each name separately.
    Defaults to the contestant name.
    """
    # Imported lazily to avoid a hard import cycle at package import time.
    from ..strategies.base import Strategy

    def decorator(cls):
        if not isinstance(cls, type):
            raise TypeError("@register must decorate a class")
        if issubclass(cls, Algo):
            kind = "event"
        elif issubclass(cls, Strategy):
            kind = "vectorized"
        else:
            raise TypeError(
                f"{cls.__name__} must subclass tradebot.arena.Algo or "
                "tradebot.strategies.Strategy to be registered"
            )

        resolved = name or getattr(cls, "name", None) or cls.__name__
        contestant = Contestant(
            name=resolved,
            factory=cls,
            kind=kind,
            author=author,
            tags=tuple(tags),
            family=family or resolved,
        )
        _REGISTRY.append(contestant)
        cls._arena_contestant = contestant  # back-reference, handy for tooling
        return cls

    return decorator
