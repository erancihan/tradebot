"""Runners execute one contestant and capture the outcome.

Two implementations behind one ``Runner`` protocol:

- ``SubprocessRunner`` — imports, builds and runs each contestant in its own
  fresh interpreter (``spawn.py``, not a fork) with a **hard** wall-clock
  timeout (the session is killed on expiry), CPU/memory ``rlimit``s and the
  sandbox. A runaway or hostile algorithm cannot stall the tournament, exhaust
  the host, or reach the parent's environment or memory. POSIX only.
- ``InProcessRunner`` — runs on a daemon thread with a **soft** ``join(timeout)``.
  Portable and fast, but Python threads can't be force-killed, so a runaway
  algo's thread keeps consuming CPU in the background (it's a daemon, so it never
  blocks process exit). It imports contestant files in-process: trusted code only.

``default_runner`` selects between them by ``isolation``:

- ``"process"`` (default) — hard isolation; **raises** if fork is unavailable
  rather than silently downgrading the guarantee to soft limits.
- ``"thread"`` — soft in-process isolation (an explicit opt-in).
- ``"auto"`` — process if possible, otherwise a *warned* fall back to thread.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Protocol

import pandas as pd

from ..risk import RiskManager
from .adapters import simulation_args
from .contestant import Contestant
from .isolation import SubprocessRunner, _error, _ok, _timeout, fork_available
from .result import ContestantResult
from .scoring import Scorer
from .simulation import SimConfig, simulate

__all__ = ["InProcessRunner", "Runner", "SubprocessRunner", "default_runner",
           "fork_available"]

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



def _simulate_contestant(contestant, frames, risk_config, config):
    """The process-isolated child's work (``child.py``), one call site with the
    in-process runner's ``simulate``."""
    policy, extra = simulation_args(contestant)
    return simulate(policy, frames, RiskManager(risk_config), config, **extra)


# --------------------------------------------------------------------------- #
# In-process (thread) runner — soft timeout, portable.
# --------------------------------------------------------------------------- #
class InProcessRunner:
    def __init__(self, time_budget_s: float = 10.0) -> None:
        self.time_budget_s = time_budget_s

    @staticmethod
    def discover(paths):
        """In-process import: module bodies run here, unsandboxed."""
        from .loader import discover

        return discover(paths)

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


def _in_process(time_budget_s, harden, seccomp, require_sandbox) -> InProcessRunner:
    """An in-process runner, refusing guarantees it cannot give.

    ``seccomp`` and ``require_sandbox`` are explicit asks for containment; a
    thread cannot have either, and dropping them behind a debug log made the
    run look sandboxed. Default-on ``harden`` stays quiet: it is not an ask.
    """
    asked = [flag for flag, on in (("--seccomp", seccomp),
                                   ("--require-sandbox", require_sandbox)) if on]
    if asked:
        raise ValueError(
            f"{' and '.join(asked)} need process isolation; an in-process (thread) "
            "runner cannot sandbox contestant code. Use --isolation process.")
    if harden:
        log.debug("hardening skipped: thread isolation can't sandbox in-process code")
    return InProcessRunner(time_budget_s)


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
        return _in_process(time_budget_s, harden, seccomp, require_sandbox)
    if not fork_available():
        if isolation == "auto":
            log.warning(
                "Hard process isolation unavailable (no 'fork' start method); falling "
                "back to soft in-process isolation — contestants are NOT killable and "
                "have no CPU/memory limits."
            )
            return _in_process(time_budget_s, harden, seccomp, require_sandbox)
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
