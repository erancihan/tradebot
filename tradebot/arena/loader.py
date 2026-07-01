"""Dynamic discovery of contestants from files or folders.

Each ``.py`` file is imported in its own throwaway module namespace via
``importlib``; any ``@register``-decorated classes it defines are collected and
attributed back to that file. A file that fails to import (syntax error, bad
import, …) is recorded as a :class:`LoadError` and skipped — one broken
submission never sinks the whole field.

Security note: importing a module runs its top-level code. This is the *trusted*
runner — only point it at algorithms you trust. The runner boundary is designed
so a sandboxed loader can replace this later for untrusted submissions.
"""

from __future__ import annotations

import importlib.util
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

from .api import _REGISTRY, clear_registry
from .contestant import Contestant


@dataclass(frozen=True)
class LoadError:
    path: str
    message: str


def _expand(paths) -> list[Path]:
    files: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            files.extend(sorted(p.glob("*.py")))
        elif p.suffix == ".py":
            files.append(p)
        else:
            raise ValueError(f"Not a .py file or directory: {raw}")
    # Skip dunder/private helper modules (e.g. __init__.py, _shared.py).
    return [f for f in files if not f.name.startswith("_")]


def _import_file(path: Path) -> None:
    module_name = f"arena_algo_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not create import spec for {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise


def discover(paths) -> tuple[list[Contestant], list[LoadError]]:
    """Import the given files/folders and return (contestants, load_errors).

    Contestant names must be unique across the field; duplicates are reported as
    load errors and dropped (keeping the first occurrence).
    """
    clear_registry()
    contestants: list[Contestant] = []
    errors: list[LoadError] = []
    seen: set[str] = set()

    for file in _expand(paths):
        before = len(_REGISTRY)
        try:
            _import_file(file)
        except Exception as exc:  # noqa: BLE001 - report and continue
            errors.append(LoadError(str(file), f"{type(exc).__name__}: {exc}"))
            continue

        for contestant in _REGISTRY[before:]:
            contestant.source = str(file)
            if contestant.name in seen:
                errors.append(
                    LoadError(str(file), f"duplicate contestant name {contestant.name!r}")
                )
                continue
            seen.add(contestant.name)
            contestants.append(contestant)

    return contestants, errors
