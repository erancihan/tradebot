"""Best-effort hardening applied *inside* a process-isolated contestant.

The child is a fresh interpreter (``tradebot.arena.child``) started with an
allow-listed environment, in an empty temporary working directory. Layered on
the CPU/memory ``rlimit``s, this removes what a hostile algorithm would want:

- **No data writes** — ``RLIMIT_FSIZE = 0``, so writing bytes to any file
  fails. It does *not* stop truncating (``open(path, "w")``) or unlinking a
  file the user owns; that is the next tier.
- **Read-only filesystem** — on Linux with Landlock (5.13+), write, create,
  remove and truncate rights exist only beneath the child's own directory
  (:mod:`tradebot.arena.landlock`). macOS has no unprivileged equivalent, so
  there a hardened child can still truncate or unlink the user's files.
- **No network** — ``unshare(CLONE_NEWNET)`` drops the process into a fresh,
  empty network namespace (only a down loopback), so it can't connect out.

Plus ``PR_SET_NO_NEW_PRIVS`` (block setuid escalation) and an open-fd cap. Each
mechanism is best-effort and guarded; ``apply_hardening`` returns a report of
what it could enforce.

For code that tries to *spawn other programs* or trace processes, ``seccomp``
is the next layer: ``apply_hardening(seccomp=True)`` loads a ``libseccomp``
filter that denies ``execve``/``execveat``/``ptrace`` with ``EPERM`` while
allowing everything else. This is opt-in (``--seccomp``).

Limits (be honest): nothing here stops a contestant from *reading* files its
user can read, including another same-user process's initial environment
(``/proc/<pid>/environ``, ``KERN_PROCARGS2``) — so never export broker keys in
the shell that runs the arena; keep them in ``.env``. Its own reply is
untrusted data (``wire.py``), and it can misreport its own result. Contestant
code is human reviewed; containers are deliberately not built (ADR 0002).
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import resource

_PR_SET_NO_NEW_PRIVS = 38
_CLONE_NEWNET = 0x40000000

# libseccomp action codes (from <seccomp.h>).
_SCMP_ACT_ALLOW = 0x7FFF0000
# Syscalls a hostile contestant would use to break out of the Python sandbox by
# launching another binary or tracing/injecting into a process. Blocking these
# with EPERM neuters ``os.system``/``subprocess``/``ptrace`` while leaving the
# numeric workload (and multiprocessing's result plumbing) untouched.
_DEFAULT_BLOCKED = ("execve", "execveat", "ptrace")


def _scmp_act_errno(errno: int) -> int:
    return 0x00050000 | (errno & 0xFFFF)


def _libc() -> ctypes.CDLL:
    return ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6", use_errno=True)


def _libc_call(libc: object, name: str, *args: int) -> bool:
    """Call a libc function; True iff the symbol exists and it returned 0.

    ``prctl`` and ``unshare`` are Linux-only. On macOS the ctypes lookup itself
    raises ``AttributeError``, which used to kill the forked contestant before
    it could report anything, so every hardened run surfaced as a misleading
    10s TIMEOUT. A missing symbol is exactly "this mechanism is not enforced
    here", so it belongs in the capability report like any other refusal.
    """
    fn = getattr(libc, name, None)
    if fn is None:
        return False
    return fn(*args) == 0


def _libseccomp() -> ctypes.CDLL:
    lib = ctypes.CDLL("libseccomp.so.2", use_errno=True)
    lib.seccomp_init.restype = ctypes.c_void_p
    lib.seccomp_init.argtypes = [ctypes.c_uint32]
    lib.seccomp_syscall_resolve_name.restype = ctypes.c_int
    lib.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    lib.seccomp_rule_add.restype = ctypes.c_int
    lib.seccomp_rule_add.argtypes = [
        ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
    lib.seccomp_load.restype = ctypes.c_int
    lib.seccomp_load.argtypes = [ctypes.c_void_p]
    lib.seccomp_release.restype = None
    lib.seccomp_release.argtypes = [ctypes.c_void_p]
    return lib


def seccomp_available() -> bool:
    """True if ``libseccomp`` can be loaded (the filter can only be *installed*
    inside a process that has set ``no_new_privs``, which ``apply_hardening``
    does)."""
    try:
        _libseccomp()
        return True
    except OSError:
        return False


def _apply_seccomp(blocked: tuple[str, ...] = _DEFAULT_BLOCKED) -> bool:
    """Install a seccomp filter denying ``blocked`` syscalls with ``EPERM`` and
    allowing everything else. Returns True iff the filter loaded. Must be called
    *after* ``PR_SET_NO_NEW_PRIVS`` so an unprivileged process is allowed to load
    it."""
    try:
        lib = _libseccomp()
    except OSError:
        return False

    ctx = lib.seccomp_init(_SCMP_ACT_ALLOW)
    if not ctx:
        return False
    try:
        deny = _scmp_act_errno(1)  # EPERM
        for name in blocked:
            nr = lib.seccomp_syscall_resolve_name(name.encode())
            if nr < 0:
                continue  # syscall unknown on this arch; skip rather than fail
            lib.seccomp_rule_add(ctx, deny, nr, 0)
        return lib.seccomp_load(ctx) == 0
    finally:
        lib.seccomp_release(ctx)


def apply_hardening(no_write: bool = True, isolate_network: bool = True,
                    no_new_privs: bool = True, max_open_files: int = 256,
                    seccomp: bool = False, writable_dir: str | None = None) -> dict:
    """Apply best-effort containment to the *current* process. Returns a report
    mapping each mechanism to whether it was enforced.

    With ``no_write`` the filesystem also goes read-only outside
    ``writable_dir`` (default: the working directory) where Landlock exists.
    When ``seccomp`` is set it is applied *last* (a seccomp load needs
    ``no_new_privs`` first) and forces ``no_new_privs`` on so the filter can load
    in an unprivileged process."""
    if seccomp or no_write:
        no_new_privs = True   # Landlock and seccomp both need it first
    report: dict[str, bool] = {}
    libc = _libc()

    if no_new_privs:
        report["no_new_privs"] = _libc_call(libc, "prctl", _PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0)

    if no_write:
        try:
            resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
            report["no_data_writes"] = True
        except (ValueError, OSError):
            report["no_data_writes"] = False
        from .landlock import restrict_writes_to

        report["read_only_fs"] = bool(report.get("no_new_privs")) and \
            restrict_writes_to(writable_dir or os.getcwd())

    if max_open_files:
        try:
            _, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
            cap = max_open_files if hard <= 0 else min(max_open_files, hard)
            resource.setrlimit(resource.RLIMIT_NOFILE, (cap, hard))
            report["limited_fds"] = True
        except (ValueError, OSError):
            report["limited_fds"] = False

    if isolate_network:
        # rc == 0 -> we entered a fresh, empty network namespace (no network).
        report["network"] = _libc_call(libc, "unshare", _CLONE_NEWNET)

    if seccomp:
        # Last: blocks execve/execveat/ptrace; needs no_new_privs (set above).
        report["seccomp"] = _apply_seccomp()

    return report


#: Environment variables a contestant must never see: every key a ``.env``
#: may set (broker keys, the batch-link signing key, the live latch, paths),
#: and anything else under the two prefixes. The child's environment is an
#: allow-list already (``spawn.child_env``); this is the second lock.
SECRET_PREFIXES = ("ALPACA_", "TRADEBOT_")


def scrub_secrets(env) -> list[str]:
    """Delete credentials, the link key and the live latch from ``env``; return names."""
    from ..credentials import DOTENV_KEYS

    names = sorted(k for k in env if k.startswith(SECRET_PREFIXES) or k in DOTENV_KEYS)
    for name in names:
        del env[name]
    return names
