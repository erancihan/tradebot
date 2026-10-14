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
from .dryrun import _run_dryrun

VALID_KINDS = ("backtest", "dryrun")


@dataclass
class Job:
    id: str
    kind: str
    state: str = "pending"          # pending -> running -> done | error
    summary: dict | None = None
    equity: dict | None = None      # {"index": [...], "equity": [...]}
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
            if kind == "backtest":
                summary, equity, provenance = _run_backtest(params)
            elif kind == "dryrun":
                summary, equity, provenance = _run_dryrun(params)
            else:
                raise ValueError(f"Unknown job kind: {kind!r}")
            self._update(job_id, state="done", summary=summary, equity=equity,
                         provenance=provenance)
        except Exception as exc:  # noqa: BLE001 - surface failures to the client
            self._update(job_id, state="error", error=f"{type(exc).__name__}: {exc}")
