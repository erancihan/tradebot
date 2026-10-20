"""The hard runner: each contestant in its own fresh, hardened interpreter.

``SubprocessRunner`` imports *and* runs every contestant in a child started by
:mod:`tradebot.arena.spawn` (not a fork), so module bodies are as sandboxed as
``on_bar`` and nothing of the parent's environment or memory is inherited.
The parent learns only names (``discover``, also in children) and reads back
plain JSON (``wire.py``). The child side is :mod:`tradebot.arena.child`.
"""

from __future__ import annotations

import logging
import math
import multiprocessing as mp
import os
import signal
import time

from .contestant import Contestant
from .loader import LoadError
from .result import ERROR, OK, TIMEOUT, ContestantResult
from .scoring import Scorer
from .spawn import Child, Died
from .wire import WireError, decode_result

log = logging.getLogger("tradebot.arena.runner")


# Shared result wrappers (both runners produce identical OK/ERROR/TIMEOUT rows).
def _ok(contestant, result, scorer: Scorer, duration: float) -> ContestantResult:
    try:
        score = float(scorer(result))
    except Exception as exc:  # noqa: BLE001 - one bad result never sinks the field
        return _error(contestant, f"scoring failed: {type(exc).__name__}: {exc}", duration)
    return ContestantResult(contestant, status=OK, score=score,
                            result=result, duration_s=duration)


def _error(contestant, message: str, duration: float) -> ContestantResult:
    return ContestantResult(contestant, status=ERROR, error=message, duration_s=duration)


def _timeout(contestant, message: str, duration: float) -> ContestantResult:
    return ContestantResult(contestant, status=TIMEOUT, error=message, duration_s=duration)


def fork_available() -> bool:
    """True on POSIX, where the hard runner's rlimits and sessions exist."""
    return "fork" in mp.get_all_start_methods()


def death_reason(exitcode: int | None) -> str:
    if exitcode is None or exitcode >= 0:
        return ""
    try:
        name = signal.Signals(-exitcode).name
    except ValueError:
        name = f"signal {-exitcode}"
    return f" (worker killed by {name})"


class SubprocessRunner:
    """Hard timeout, CPU/memory limits and optional sandbox, per contestant."""

    def __init__(self, time_budget_s: float = 10.0,
                 cpu_seconds: int | None = None, memory_mb: int | None = None,
                 harden: bool = False, seccomp: bool = False,
                 require_sandbox: bool = False) -> None:
        if not fork_available():
            raise RuntimeError("SubprocessRunner requires the 'fork' start method (POSIX).")
        self.time_budget_s = time_budget_s
        # Default a CPU cap derived from the wall budget so a busy-loop is also
        # stopped by SIGXCPU even before the wall-clock kill.
        self.cpu_seconds = cpu_seconds if cpu_seconds is not None else int(math.ceil(time_budget_s)) + 1
        self.memory_mb = memory_mb
        self.harden = harden
        self.seccomp = seccomp
        self.require_sandbox = require_sandbox
        #: Containment that was asked for and could not be enforced, collected
        #: across runs so a caller can report it once rather than per contestant.
        self.degraded: set[str] = set()
        #: Tests only: mechanisms the child reports as refused.
        self._pretend_unenforced: tuple[str, ...] = ()

    def _request(self, mode: str, source: str, **extra) -> dict:
        # Absolute: the child works in its own empty directory.
        return {"mode": mode, "source": os.path.abspath(source),
                "cpu_seconds": self.cpu_seconds,
                "memory_mb": self.memory_mb, "harden": self.harden,
                "seccomp": self.seccomp, "require_sandbox": self.require_sandbox,
                "pretend_unenforced": list(self._pretend_unenforced), **extra}

    def _exchange(self, child: Child):
        """(reply | Died | WireError | None, seconds since ready)."""
        ready = child.wait_ready()
        if ready is not True:
            return ready, 0.0
        child.go()
        start = time.perf_counter()
        return child.reply(self.time_budget_s), time.perf_counter() - start

    def run(self, contestant, frames, risk, config, scorer) -> ContestantResult:
        return self.run_all([contestant], frames, risk, config, scorer)[0]

    def run_all(self, contestants, frames, risk, config, scorer) -> list[ContestantResult]:
        """One at a time, the next one's interpreter starting while this one runs."""
        def launch(c):
            if not c.source:
                return None
            return Child(self._request("run", c.source, name=c.name, frames=frames,
                                       risk_config=risk.config, config=config))

        results, upcoming = [], launch(contestants[0]) if contestants else None
        try:
            for i, contestant in enumerate(contestants):
                child = upcoming
                upcoming = launch(contestants[i + 1]) if i + 1 < len(contestants) else None
                results.append(self._run_child(contestant, child, scorer))
        finally:
            if upcoming is not None:   # interrupted: never leave one waiting
                upcoming.close()
        return results

    def _run_child(self, contestant, child, scorer) -> ContestantResult:
        if child is None:
            return _error(contestant, "process isolation runs contestants loaded "
                          "from a file (no source)", 0.0)
        try:
            reply, duration = self._exchange(child)
            if reply is None:
                reason = death_reason(child.proc.poll())
                return _timeout(contestant, f"exceeded {self.time_budget_s:g}s{reason}",
                                duration)
        finally:
            child.close()
        return self._outcome(contestant, reply, scorer, duration)

    def _outcome(self, contestant, reply, scorer, duration) -> ContestantResult:
        if isinstance(reply, Died):
            if reply.returncode == -signal.SIGXCPU:
                return _timeout(contestant, "exceeded its CPU limit", duration)
            return _error(contestant, "worker exited before replying (exit code "
                          f"{reply.returncode}){death_reason(reply.returncode)}", duration)
        if isinstance(reply, WireError):
            return _error(contestant, f"rejected reply: {reply}", duration)
        self._report_degraded(reply["denied"])
        if reply["status"] != "ok":
            return _error(contestant, reply["error"], duration)
        try:
            result = decode_result(reply["result"])
        except WireError as exc:
            return _error(contestant, f"rejected reply: {exc}", duration)
        return _ok(contestant, result, scorer, duration)

    def discover(self, paths) -> tuple[list[Contestant], list[LoadError]]:
        """Names only, from hardened children: no module body runs in the parent."""
        from .isolated_discovery import discover_isolated

        return discover_isolated(self, paths)

    def _report_degraded(self, denied) -> None:
        """Loud, and only once per mechanism: a per-contestant warning would
        print twelve identical lines and train everyone to ignore it."""
        for mechanism in denied or ():
            if mechanism not in self.degraded:
                self.degraded.add(mechanism)
                log.warning(
                    "sandbox: %r could NOT be enforced in this environment; "
                    "contestants are running with that containment missing. "
                    "Pass --require-sandbox to make this a hard failure.",
                    mechanism)
