"""Process-isolation mechanics for the hard runner (POSIX/fork).

Everything that touches a forked child lives here: ``SubprocessRunner``,
resource limits, the child entrypoint with its optional sandbox, and
killing/diagnosing the worker. What the child actually *runs* is passed to
``subprocess_work`` as a callable (``runner._simulate_contestant``), so the
simulation call site stays in :mod:`tradebot.arena.runner`.
"""

from __future__ import annotations

import logging
import math
import multiprocessing as mp
import queue as queue_mod
import time

from .result import ERROR, OK, TIMEOUT, ContestantResult
from .scoring import Scorer

log = logging.getLogger("tradebot.arena.runner")


# Shared result wrappers (both runners produce identical OK/ERROR/TIMEOUT rows).
def _ok(contestant, result, scorer: Scorer, duration: float) -> ContestantResult:
    return ContestantResult(contestant, status=OK, score=float(scorer(result)),
                            result=result, duration_s=duration)


def _error(contestant, message: str, duration: float) -> ContestantResult:
    return ContestantResult(contestant, status=ERROR, error=message, duration_s=duration)


def _timeout(contestant, message: str, duration: float) -> ContestantResult:
    return ContestantResult(contestant, status=TIMEOUT, error=message, duration_s=duration)


def fork_available() -> bool:
    return "fork" in mp.get_all_start_methods()


def _apply_limits(cpu_seconds: int | None, memory_mb: int | None) -> None:
    try:
        import resource
    except ImportError:  # non-POSIX
        return
    try:
        if cpu_seconds:
            resource.setrlimit(resource.RLIMIT_CPU, (int(cpu_seconds), int(cpu_seconds)))
        if memory_mb:
            nbytes = int(memory_mb) * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (nbytes, nbytes))
    except (ValueError, OSError):
        pass


def subprocess_work(work, contestant, frames, risk_config, config, result_queue,
                    cpu_seconds, memory_mb, harden, seccomp,
                    require_sandbox=False) -> None:
    """Child entrypoint: apply limits, optionally sandbox, run ``work``, ship back."""
    _apply_limits(cpu_seconds, memory_mb)
    denied: list[str] = []
    if harden or seccomp:
        from .sandbox import apply_hardening

        # ``seccomp`` is the adversarial tier; it can be requested on its own, but
        # we still keep the default no-write/no-network layers on when hardening.
        report = apply_hardening(no_write=harden, isolate_network=harden,
                                 max_open_files=256 if harden else 0, seccomp=seccomp)
        # Never silently downgrade. The capability report used to be discarded
        # entirely, so a failed `unshare(CLONE_NEWNET)` left the contestant with
        # full network access while the tournament printed a clean `ok`.
        #
        # But "never silent" is satisfied by *reporting*, not by refusing to run.
        # Refusing made the arena unusable anywhere the kernel will not grant a
        # network namespace to an unprivileged process — CI runners, ordinary
        # containers, macOS — which is not a threat model, it is a portability
        # bug. Contestant code here is human-reviewed (see the deferred
        # container tier in CLAUDE.md), so the default is to run and say so
        # loudly; `require_sandbox` turns it into a hard failure for anyone
        # whose threat model actually needs the guarantee.
        denied = sorted(k for k, enforced in report.items() if not enforced)
        if denied and require_sandbox:
            result_queue.put(("error",
                              "SandboxError: requested containment not enforced: "
                              + ", ".join(denied), denied))
            return
    try:
        result = work(contestant, frames, risk_config, config)
        result_queue.put(("ok", result, denied))
    except BaseException as exc:  # noqa: BLE001 - incl. MemoryError; isolate
        result_queue.put(("error", f"{type(exc).__name__}: {exc}", denied))


def kill(proc) -> None:
    if proc.is_alive():
        proc.terminate()
        proc.join(1.0)
    if proc.is_alive():
        proc.kill()
        proc.join(1.0)


def death_reason(exitcode: int | None) -> str:
    if exitcode is None or exitcode >= 0:
        return ""
    import signal
    try:
        name = signal.Signals(-exitcode).name
    except ValueError:
        name = f"signal {-exitcode}"
    return f" (worker killed by {name})"


# --------------------------------------------------------------------------- #
# Subprocess runner — hard timeout + resource limits (POSIX/fork).
# --------------------------------------------------------------------------- #
class SubprocessRunner:
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
        self._ctx = mp.get_context("fork")

    def run(self, contestant, frames, risk, config, scorer) -> ContestantResult:
        start = time.perf_counter()
        result_queue = self._ctx.Queue()
        # Resolved through the runner module at call time, so a test that wraps
        # `runner.simulate` sees subprocess runs too.
        from .runner import _simulate_contestant

        proc = self._ctx.Process(
            target=subprocess_work,
            args=(_simulate_contestant, contestant, frames, risk.config, config,
                  result_queue, self.cpu_seconds, self.memory_mb, self.harden,
                  self.seccomp, self.require_sandbox),
            name=f"arena-{contestant.name}", daemon=True,
        )
        proc.start()

        # Consume the result with the budget; consuming avoids the classic
        # "process won't exit until its queue is drained" deadlock.
        try:
            message = result_queue.get(timeout=self.time_budget_s)
        except queue_mod.Empty:
            message = None
        duration = time.perf_counter() - start

        if message is None:
            kill(proc)
            reason = death_reason(proc.exitcode)
            return _timeout(contestant, f"exceeded {self.time_budget_s:g}s{reason}", duration)

        proc.join(1.0)
        if proc.is_alive():
            kill(proc)

        status, payload, denied = message
        self._report_degraded(denied)
        if status == "ok":
            return _ok(contestant, payload, scorer, duration)
        return _error(contestant, str(payload), duration)

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

    # Kept as static methods for callers that used them; the logic lives in
    # `isolation` with the rest of the process mechanics.
    _kill = staticmethod(kill)
    _death_reason = staticmethod(death_reason)
