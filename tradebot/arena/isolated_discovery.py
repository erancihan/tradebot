"""Discovery under process isolation: import each file in a hardened child.

A module body is contestant code. The in-process loader ran it in the parent
before any sandbox existed, so a body could read and write whatever the
parent could. Here each file is imported in its own fresh, hardened
interpreter (side by side, each with its own deadline) and only plain
metadata comes back; the parent never imports the file. The contestant is
imported again, and built, inside the child that runs it.
"""

from __future__ import annotations

from .contestant import Contestant
from .loader import LoadError, _expand
from .spawn import Child, Died
from .wire import WireError, decode_discovery


def _built_in_child():
    raise RuntimeError("a process-isolated contestant is built only inside its sandbox")


def _discovered(runner, file: str, reply):
    if reply is None:
        return [], [(file, f"import exceeded {runner.time_budget_s:g}s")]
    if isinstance(reply, Died):
        return [], [(file, f"import worker exited (exit code {reply.returncode})")]
    if isinstance(reply, WireError):
        return [], [(file, f"rejected reply: {reply}")]
    runner._report_degraded(reply["denied"])
    if reply["status"] != "ok":
        return [], [(file, reply["error"])]
    try:
        return decode_discovery(reply["result"])
    except WireError as exc:
        return [], [(file, f"rejected reply: {exc}")]


def discover_isolated(runner, paths) -> tuple[list[Contestant], list[LoadError]]:
    """``loader.discover``'s contract (unique names, errors not raised), sandboxed."""
    files = [str(f) for f in _expand(paths)]
    children = [Child(runner._request("discover", f)) for f in files]
    for child in children:
        child.go()
    found: list[Contestant] = []
    errors: list[LoadError] = []
    seen: set[str] = set()
    for file, child in zip(files, children):
        try:
            reply, _ = runner._exchange(child)
        finally:
            child.close()
        metas, errs = _discovered(runner, file, reply)
        errors.extend(LoadError(p, m) for p, m in errs)
        for meta in metas:
            if meta["name"] in seen:
                errors.append(LoadError(file, f"duplicate contestant name {meta['name']!r}"))
                continue
            seen.add(meta["name"])
            found.append(Contestant(factory=_built_in_child, source=file, **meta))
    return found, errors
