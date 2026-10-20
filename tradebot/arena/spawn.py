"""Start a fresh contestant interpreter and read its reply, with deadlines.

Not a fork: a forked child holds the parent's heap (loaded credential
objects) and its initial environment block, which ``unsetenv`` never clears.
A new interpreter gets an allow-listed environment, an empty temporary
working directory, its own session (so a kill reaches anything it forks), and
only the request the parent writes to its stdin.
"""

from __future__ import annotations

import os
import pickle
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from .sandbox import scrub_secrets
from .wire import MAX_REPLY_BYTES, WireError, decode_reply

#: The directory that holds the ``tradebot`` package the parent runs.
_ROOT = str(Path(__file__).resolve().parents[2])
_BOOT = ("import sys; sys.path.insert(0, sys.argv[1]); "
         "from tradebot.arena.child import main; main()")
_ENV_KEEP = ("PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TZ")
#: Interpreter start-up is not the contestant's time; allow a slow machine.
STARTUP_S = 60.0
REQUEST_FILE = "request.pickle"


def child_env() -> dict[str, str]:
    """An allow-list, not a copy: nothing the parent loaded can leak through."""
    env = {k: os.environ[k] for k in _ENV_KEEP if k in os.environ}
    env.update(PYTHONHASHSEED="0", PYTHONSAFEPATH="1", PYTHONDONTWRITEBYTECODE="1",
               PYTHONNOUSERSITE="1")
    scrub_secrets(env)
    return env


@dataclass
class Died:
    """The child exited (or was killed) before replying."""

    returncode: int | None


class Child:
    """One contestant interpreter: launch, ``wait_ready``, ``reply``, ``close``."""

    def __init__(self, request: dict) -> None:
        self.workdir = tempfile.mkdtemp(prefix="arena-")
        self.started = time.monotonic()
        self._buf = b""
        # The request goes in a file, not the pipe, so launching never blocks
        # on a child still importing: the next contestant starts up while the
        # current one runs. The child reads and deletes it before hardening.
        path = os.path.join(self.workdir, REQUEST_FILE)
        with open(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as fh:
            pickle.dump(request, fh, protocol=pickle.HIGHEST_PROTOCOL)
        self.proc = subprocess.Popen(
            [sys.executable, "-s", "-c", _BOOT, _ROOT], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, env=child_env(), cwd=self.workdir,
            start_new_session=True, close_fds=True)

    def go(self) -> None:
        """Let a ready child start: limits, hardening, then contestant code."""
        if self.proc.stdin.closed:
            return
        try:
            self.proc.stdin.write(b"g")
            self.proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass   # it died at start-up; the read reports how

    def wait_ready(self) -> object:
        """True once the child is ready, else ``Died``, ``None`` (no answer) or a WireError."""
        line = self._line(self.started + STARTUP_S)
        if isinstance(line, bytes):
            return True if line.strip() == b'{"ready": true}' else WireError("no ready line")
        return line

    def reply(self, budget_s: float) -> object:
        """The decoded reply, ``Died``, ``None`` on timeout, or a ``WireError``."""
        line = self._line(time.monotonic() + budget_s)
        if isinstance(line, bytes):
            try:
                return decode_reply(line)
            except WireError as exc:
                return exc
        return line

    def _line(self, deadline: float):
        fd = self.proc.stdout.fileno()
        while b"\n" not in self._buf:
            if len(self._buf) > MAX_REPLY_BYTES:
                return WireError("reply too large")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            readable, _, _ = select.select([fd], [], [], min(remaining, 0.05))
            if readable:
                chunk = os.read(fd, 1 << 20)
                if chunk:
                    self._buf += chunk
                    continue
            # EOF, or silence after the child is gone (a grandchild may still
            # hold the pipe): it died before replying. Do not wait the budget.
            if (readable or self.proc.poll() is not None) and not self._drain(fd):
                return Died(self._exit_code())
        line, _, self._buf = self._buf.partition(b"\n")
        return line

    def _drain(self, fd) -> bool:
        readable, _, _ = select.select([fd], [], [], 0)
        if not readable:
            return False
        chunk = os.read(fd, 1 << 20)
        self._buf += chunk
        return bool(chunk)

    def _exit_code(self) -> int | None:
        try:
            return self.proc.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            return None

    def close(self) -> None:
        """Kill the child's whole session, reap it, remove its directory."""
        if not self.proc.stdin.closed:
            self.proc.stdin.close()
        try:
            os.killpg(self.proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            self.proc.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            pass
        self.proc.stdout.close()
        shutil.rmtree(self.workdir, ignore_errors=True)
