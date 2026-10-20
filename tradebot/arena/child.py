"""The process-isolated contestant's side: a fresh interpreter, then hardening.

``spawn.py`` starts ``python -s -c <boot>`` with an allow-listed environment in
an empty temporary directory, so nothing of the parent is inherited: no
credential object, no ``os.environ``, no initial environment block. Order:

1. read and delete the request (the parent's own data, pickled) in its
   working directory;
2. move stdout aside as the reply channel, so a ``print`` cannot corrupt it;
3. say ``ready`` and wait for the parent's go on stdin — the time budget
   starts there, not at interpreter start;
4. limits, secret scrub, hardening (``no_new_privs`` before Landlock and
   seccomp, inside ``apply_hardening``);
5. only then import the contestant file and build it, so its module body is
   as sandboxed as its ``on_bar``;
6. reply with one line of plain JSON (``wire.py``).
"""

from __future__ import annotations

import math
import os
import pickle
import sys

from .loader import discover
from .spawn import REQUEST_FILE
from .runner import _simulate_contestant
from .wire import encode_line, encode_result


def _apply_limits(cpu_seconds: int | None, memory_mb: int | None) -> None:
    try:
        import resource
    except ImportError:  # non-POSIX
        return
    try:
        if cpu_seconds:
            # RLIMIT_CPU counts the whole process; start-up already used some.
            used = resource.getrusage(resource.RUSAGE_SELF)
            cap = int(math.ceil(used.ru_utime + used.ru_stime)) + int(cpu_seconds)
            resource.setrlimit(resource.RLIMIT_CPU, (cap, cap))
        if memory_mb:
            nbytes = int(memory_mb) * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (nbytes, nbytes))
    except (ValueError, OSError):
        pass


def _harden(request: dict) -> list[str]:
    """Apply the requested containment; return the mechanisms it could not get."""
    harden, seccomp = request["harden"], request["seccomp"]
    if not (harden or seccomp):
        return []
    from .sandbox import apply_hardening

    # ``seccomp`` can be asked for alone; the no-write/no-network layers stay
    # tied to ``harden``.
    report = apply_hardening(no_write=harden, isolate_network=harden,
                             max_open_files=256 if harden else 0, seccomp=seccomp,
                             writable_dir=os.getcwd())
    for mechanism in request.get("pretend_unenforced", ()):   # tests only
        report[mechanism] = False
    return sorted(k for k, enforced in report.items() if not enforced)


def _work(request: dict):
    found, errors = discover([request["source"]])
    if request["mode"] == "discover":
        return {"contestants": [{"name": c.name, "kind": c.kind, "author": c.author,
                                 "tags": list(c.tags), "family": c.family}
                                for c in found],
                "errors": [[e.path, e.message] for e in errors]}
    match = [c for c in found if c.name == request["name"]]
    if not match:
        reason = "; ".join(e.message for e in errors) or "not registered"
        raise LookupError(f"contestant {request['name']!r} not loaded: {reason}")
    result = _simulate_contestant(match[0], request["frames"], request["risk_config"],
                                  request["config"])
    return encode_result(result)


def main() -> None:
    # Unpickling is safe in this direction: the request is the parent's own
    # data (frames, configs), written before any contestant code exists here.
    with open(REQUEST_FILE, "rb") as fh:
        request = pickle.load(fh)
    os.unlink(REQUEST_FILE)
    reply = os.fdopen(os.dup(1), "wb", buffering=0)
    os.dup2(2, 1)                      # contestant prints go to stderr

    def send(message: dict) -> None:
        reply.write(encode_line(message))

    send({"ready": True})
    if sys.stdin.buffer.read(1) != b"g":   # the parent's go; EOF means stop
        return
    _apply_limits(request["cpu_seconds"], request["memory_mb"])
    from .sandbox import scrub_secrets

    scrub_secrets(os.environ)
    denied = _harden(request)
    if denied and request["require_sandbox"]:
        send({"status": "error", "denied": denied,
              "error": "SandboxError: requested containment not enforced: "
                       + ", ".join(denied)})
        return
    try:
        send({"status": "ok", "result": _work(request), "denied": denied})
    except BaseException as exc:  # noqa: BLE001 - incl. MemoryError; isolate
        send({"status": "error", "error": f"{type(exc).__name__}: {exc}",
              "denied": denied})
