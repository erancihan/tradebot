"""In-process job registry: submit, poll, and run jobs on a small thread pool.

State is a single dict guarded by a lock — fine for a local, single-user
dashboard; a multi-process deployment would swap this for a shared queue, which
is why the registry is the only thing routes touch.
"""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from .backtest import _run_backtest
from .discover import _run_discover
from .dryrun import _run_dryrun
from .proposal import _run_proposal

from .whatif import _run_whatif
from .whatif_compare import _run_whatif_compare

#: Kinds the generic Run page may submit. ``whatif``, ``whatif_compare``,
#: ``proposal`` and ``discover`` have their own endpoints, so the registry
#: accepts them but they are not listed here.
VALID_KINDS = ("backtest", "dryrun")

_RUNNERS = {"backtest": _run_backtest, "dryrun": _run_dryrun,
            "proposal": _run_proposal, "whatif": _run_whatif,
            "whatif_compare": _run_whatif_compare, "discover": _run_discover}


def _as_fields(outcome) -> dict:
    """Runners return either the classic (summary, equity, provenance) tuple
    or a dict of Job fields (what-if adds a benchmark curve)."""
    if isinstance(outcome, dict):
        return outcome
    summary, equity, provenance = outcome
    return {"summary": summary, "equity": equity, "provenance": provenance}


@dataclass
class Job:
    id: str
    kind: str
    state: str = "pending"          # pending -> running -> done | error
    summary: dict | None = None
    equity: dict | None = None      # {"index": [...], "equity": [...]}
    benchmark: dict | None = None   # what-if only: the comparison curve
    compare: dict | None = None     # whatif_compare only: ranked rows and curves
    provenance: dict | None = None  # what data this ran on — travels with the result
    error: str | None = None


class JobRegistry:
    def __init__(self, max_workers: int = 2) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=max_workers)

    def submit(self, kind: str, params: dict) -> str:
        job = Job(id=uuid.uuid4().hex[:12], kind=kind)
        with self._lock:
            self._jobs[job.id] = job
        self._pool.submit(self._run, job.id, kind, params)
        return job.id

    def find_active(self, kind: str) -> str | None:
        """The id of a pending or running job of ``kind``, if there is one."""
        with self._lock:
            return self._active(kind)

    def submit_once(self, kind: str, params: dict) -> str:
        """Single flight: reuse a pending or running ``kind`` job, else submit.

        Check and insert happen under one lock, so two taps racing each other
        still start one job.
        """
        with self._lock:
            active = self._active(kind)
            if active is not None:
                return active
            job = Job(id=uuid.uuid4().hex[:12], kind=kind)
            self._jobs[job.id] = job
        self._pool.submit(self._run, job.id, kind, params)
        return job.id

    def _active(self, kind: str) -> str | None:
        return next((j.id for j in self._jobs.values()
                     if j.kind == kind and j.state in ("pending", "running")), None)

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def _update(self, job_id: str, **changes) -> None:
        with self._lock:
            job = self._jobs[job_id]
            for key, value in changes.items():
                setattr(job, key, value)

    def _run(self, job_id: str, kind: str, params: dict) -> None:
        self._update(job_id, state="running")
        try:
            runner = _RUNNERS.get(kind)
            if runner is None:
                raise ValueError(f"Unknown job kind: {kind!r}")
            self._update(job_id, state="done", **_as_fields(runner(params)))
        except Exception as exc:  # noqa: BLE001 - surface failures to the client
            self._update(job_id, state="error", error=_error_text(exc))


#: Raised on purpose with a sentence for the person (no bars cached, a bad
#: symbol): the sentence is the message. Exact types only: a subclass such as
#: ``DailyLossLimitError`` or ``JSONDecodeError`` keeps its name as the clue,
#: as does anything else ("KeyError: 'close'" is the whole clue).
_EXPECTED = (RuntimeError, ValueError)


def _error_text(exc: Exception) -> str:
    if type(exc) in _EXPECTED and str(exc):
        return str(exc)
    # The registries raise KeyError("Unknown strategy 'x'. Known: ...");
    # str() would wrap that sentence in quotes, so show the sentence itself.
    first = exc.args[0] if type(exc) is KeyError and exc.args else None
    if isinstance(first, str) and " " in first:
        return first
    return f"{type(exc).__name__}: {exc}"
