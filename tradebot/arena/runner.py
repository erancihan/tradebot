"""Runners execute one contestant and capture the outcome.

Two implementations behind one ``Runner`` protocol:

- ``SubprocessRunner`` — runs each contestant in its own forked process with a
  **hard** wall-clock timeout (the process is killed on expiry) plus optional
  CPU/memory ``rlimit``s. Real isolation: a runaway or hostile algorithm cannot
  stall the tournament or exhaust the host. POSIX/fork only.
- ``InProcessRunner`` — runs on a daemon thread with a **soft** ``join(timeout)``.
  Portable and fast, but Python threads can't be force-killed, so a runaway
  algo's thread keeps consuming CPU in the background (it's a daemon, so it never
  blocks process exit). Use for trusted code, or where fork isn't available.

``default_runner`` selects between them by ``isolation``:

- ``"process"`` (default) — hard isolation; **raises** if fork is unavailable
  rather than silently downgrading the guarantee to soft limits.
- ``"thread"`` — soft in-process isolation (an explicit opt-in).
- ``"auto"`` — process if possible, otherwise a *warned* fall back to thread.
"""

from __future__ import annotations

import logging
import math
import multiprocessing as mp
import queue as queue_mod
import threading
import time
from typing import Protocol

import pandas as pd

from ..risk import RiskManager
from .adapters import simulation_args
from .contestant import Contestant
from .result import ERROR, OK, TIMEOUT, ContestantResult
from .scoring import Scorer
from .simulation import SimConfig, simulate

log = logging.getLogger("tradebot.arena.runner")

_ISOLATION_MODES = ("process", "thread", "auto")


class Runner(Protocol):
    def run(
        self,
        contestant: Contestant,
        frames: dict[str, pd.DataFrame],
        risk: RiskManager,
        config: SimConfig,
        scorer: Scorer,
    ) -> ContestantResult: ...


# Shared result wrappers (both runners produce identical OK/ERROR/TIMEOUT rows).
def _ok(contestant, result, scorer: Scorer, duration: float) -> ContestantResult:
    return ContestantResult(contestant, status=OK, score=float(scorer(result)),
                            result=result, duration_s=duration)


def _error(contestant, message: str, duration: float) -> ContestantResult:
    return ContestantResult(contestant, status=ERROR, error=message, duration_s=duration)


def _timeout(contestant, message: str, duration: float) -> ContestantResult:
    return ContestantResult(contestant, status=TIMEOUT, error=message, duration_s=duration)


# --------------------------------------------------------------------------- #
# In-process (thread) runner — soft timeout, portable.
# --------------------------------------------------------------------------- #
class InProcessRunner:
    def __init__(self, time_budget_s: float = 10.0) -> None:
        self.time_budget_s = time_budget_s

    def run(self, contestant, frames, risk, config, scorer) -> ContestantResult:
        start = time.perf_counter()
        box: dict[str, object] = {}

        def work() -> None:
            try:
                policy, extra = simulation_args(contestant)
                box["result"] = simulate(policy, frames, risk, config, **extra)
            except Exception as exc:  # noqa: BLE001 - reported via box, isolated
                box["error"] = exc

        thread = threading.Thread(target=work, name=f"arena-{contestant.name}", daemon=True)
        thread.start()
        thread.join(self.time_budget_s)
        duration = time.perf_counter() - start

        if thread.is_alive():
            return _timeout(contestant, f"exceeded {self.time_budget_s:g}s (soft)", duration)
        if "error" in box:
            exc = box["error"]
            return _error(contestant, f"{type(exc).__name__}: {exc}", duration)
        return _ok(contestant, box["result"], scorer, duration)


# --------------------------------------------------------------------------- #
# Subprocess runner — hard timeout + resource limits (POSIX/fork).
# --------------------------------------------------------------------------- #
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


def _subprocess_work(contestant, frames, risk_config, config, result_queue,
                     cpu_seconds, memory_mb, harden, seccomp,
                     require_sandbox=False) -> None:
    """Child entrypoint: apply limits, optionally sandbox, simulate, ship back."""
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
        policy, extra = simulation_args(contestant)
        result = simulate(policy, frames, RiskManager(risk_config), config, **extra)
        result_queue.put(("ok", result, denied))
    except BaseException as exc:  # noqa: BLE001 - incl. MemoryError; isolate
        result_queue.put(("error", f"{type(exc).__name__}: {exc}", denied))


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
        proc = self._ctx.Process(
            target=_subprocess_work,
            args=(contestant, frames, risk.config, config, result_queue,
                  self.cpu_seconds, self.memory_mb, self.harden, self.seccomp,
                  self.require_sandbox),
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
            self._kill(proc)
            reason = self._death_reason(proc.exitcode)
            return _timeout(contestant, f"exceeded {self.time_budget_s:g}s{reason}", duration)

        proc.join(1.0)
        if proc.is_alive():
            self._kill(proc)

        status, payload, denied = message
        if denied:
            # Loud, and only once per mechanism: a per-contestant warning would
            # print twelve identical lines and train everyone to ignore it.
            for mechanism in denied:
                if mechanism not in self.degraded:
                    self.degraded.add(mechanism)
                    log.warning(
                        "sandbox: %r could NOT be enforced in this environment; "
                        "contestants are running with that containment missing. "
                        "Pass --require-sandbox to make this a hard failure.",
                        mechanism)
        if status == "ok":
            return _ok(contestant, payload, scorer, duration)
        return _error(contestant, str(payload), duration)

    @staticmethod
    def _kill(proc) -> None:
        if proc.is_alive():
            proc.terminate()
            proc.join(1.0)
        if proc.is_alive():
            proc.kill()
            proc.join(1.0)

    @staticmethod
    def _death_reason(exitcode: int | None) -> str:
        if exitcode is None or exitcode >= 0:
            return ""
        import signal
        try:
            name = signal.Signals(-exitcode).name
        except ValueError:
            name = f"signal {-exitcode}"
        return f" (worker killed by {name})"


def default_runner(time_budget_s: float = 10.0, isolation: str = "process",
                   cpu_seconds: int | None = None, memory_mb: int | None = None,
                   harden: bool = True, seccomp: bool = False,
                   require_sandbox: bool = False) -> Runner:
    """Select a runner from an isolation mode.

    - ``"process"`` (default): hard subprocess isolation. **Raises** if fork is
      unavailable — it never silently downgrades a hard guarantee to soft limits.
      With ``harden=True`` the child is additionally sandboxed (no disk writes,
      no network) — see :mod:`tradebot.arena.sandbox`. ``seccomp=True`` adds the
      adversarial tier: a syscall filter denying ``execve``/``ptrace``.
      Containment the kernel refuses to grant (commonly a network namespace, in
      CI and unprivileged containers) is **reported loudly and once**, not
      silently dropped; pass ``require_sandbox=True`` to make it fatal instead.
    - ``"thread"``: the soft in-process runner (explicit opt-in to weak limits).
    - ``"auto"``: process if fork is available, otherwise a warned fall back to
      the in-process runner.
    """
    if isolation not in _ISOLATION_MODES:
        raise ValueError(
            f"Unknown isolation {isolation!r}; expected one of {_ISOLATION_MODES}."
        )
    if isolation == "thread":
        if harden or seccomp:
            # Default-on hardening simply doesn't apply to in-process execution;
            # keep this quiet (debug) so the common thread path isn't noisy.
            log.debug("hardening skipped: thread isolation can't sandbox in-process code")
        return InProcessRunner(time_budget_s)
    if not fork_available():
        if isolation == "auto":
            log.warning(
                "Hard process isolation unavailable (no 'fork' start method); falling "
                "back to soft in-process isolation — contestants are NOT killable and "
                "have no CPU/memory limits."
            )
            return InProcessRunner(time_budget_s)
        # isolation == "process": refuse to silently weaken the guarantee.
        raise RuntimeError(
            "Hard process isolation requires the 'fork' start method, which is "
            "unavailable on this platform. Re-run with --isolation thread to accept "
            "soft (non-killable, unlimited) limits, or --isolation auto to fall back "
            "automatically."
        )
    return SubprocessRunner(time_budget_s, cpu_seconds, memory_mb,
                            harden=harden, seccomp=seccomp,
                            require_sandbox=require_sandbox)
