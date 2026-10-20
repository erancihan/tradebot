"""Landlock: a read-only filesystem for the hardened child (Linux only).

``RLIMIT_FSIZE=0`` stops a child from writing data, but not from truncating
(``open(path, "w")``) or unlinking a file its user owns. Landlock (Linux 5.13+,
unprivileged) can: the child keeps read access everywhere and gets write,
create, remove and truncate rights only beneath its own empty working
directory. Kernels without it, and macOS, report the tier as not enforced.

Raw syscalls through ``ctypes``: there is no libc wrapper. The numbers are
the same on every architecture the kernel added Landlock to after the
syscall-table unification (444, 445, 446).
"""

from __future__ import annotations

import ctypes
import os
import sys

_SYS_CREATE_RULESET, _SYS_ADD_RULE, _SYS_RESTRICT_SELF = 444, 445, 446
_CREATE_RULESET_VERSION = 1
_RULE_PATH_BENEATH = 1

# Filesystem rights that change something (bits from <linux/landlock.h>).
# Reads (EXECUTE, READ_FILE, READ_DIR) are left unhandled, so stay allowed.
_WRITE_FILE = 1 << 1
_ABI1_WRITES = (_WRITE_FILE | 1 << 4 | 1 << 5 | 1 << 6 | 1 << 7 | 1 << 8 | 1 << 9
                | 1 << 10 | 1 << 11 | 1 << 12)   # remove dir/file, make char..sym
_REFER = 1 << 13      # ABI 2: link or rename across directories
_TRUNCATE = 1 << 14   # ABI 3: truncate(2) and O_TRUNC


class _RulesetAttr(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64)]


class _PathBeneathAttr(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32)]


def _syscall():
    libc = ctypes.CDLL(None, use_errno=True)
    fn = getattr(libc, "syscall", None)
    if fn is not None:
        fn.restype = ctypes.c_long
    return fn


def landlock_abi() -> int:
    """The kernel's Landlock ABI version, or 0 where it is unavailable."""
    if not sys.platform.startswith("linux"):
        return 0
    fn = _syscall()
    if fn is None:
        return 0
    abi = fn(ctypes.c_long(_SYS_CREATE_RULESET), None, ctypes.c_size_t(0),
             ctypes.c_uint32(_CREATE_RULESET_VERSION))
    return max(int(abi), 0)


def _handled(abi: int) -> int:
    rights = _ABI1_WRITES
    if abi >= 2:
        rights |= _REFER
    if abi >= 3:
        rights |= _TRUNCATE
    return rights


def restrict_writes_to(directory: str) -> bool:
    """Make every path but ``directory`` read-only for this process, for good.

    Needs ``no_new_privs`` first (``apply_hardening`` sets it). True iff the
    ruleset is in force; any refusal leaves the process unchanged.
    """
    abi = landlock_abi()
    if abi < 1:
        return False
    fn = _syscall()
    rights = _handled(abi)
    attr = _RulesetAttr(rights)
    ruleset = fn(ctypes.c_long(_SYS_CREATE_RULESET), ctypes.byref(attr),
                 ctypes.c_size_t(ctypes.sizeof(attr)), ctypes.c_uint32(0))
    if ruleset < 0:
        return False
    try:
        dir_fd = os.open(directory, os.O_PATH | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            rule = _PathBeneathAttr(rights, dir_fd)
            if fn(ctypes.c_long(_SYS_ADD_RULE), ctypes.c_int(ruleset),
                  ctypes.c_int(_RULE_PATH_BENEATH), ctypes.byref(rule),
                  ctypes.c_uint32(0)) != 0:
                return False
        finally:
            os.close(dir_fd)
        return fn(ctypes.c_long(_SYS_RESTRICT_SELF), ctypes.c_int(ruleset),
                  ctypes.c_uint32(0)) == 0
    finally:
        os.close(ruleset)
