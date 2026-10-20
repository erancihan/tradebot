"""Process isolation boundary: what a hostile contestant can and cannot reach.

Each test here was written against a reproduced attack (review 14): a module
body that ran in the parent, a reply that unpickled code in the parent, a
child that inherited the parent's environment and memory, a hardened child
that could still truncate files, and a dead child waited out as a timeout.
"""

from __future__ import annotations

import os
import sys
import time

import pytest

from tradebot.arena.runner import SubprocessRunner, fork_available
from tradebot.arena.scenario import Scenario
from tradebot.arena.tournament import run_tournament

from .arena_files import algo_file, run_file

needs_process = pytest.mark.skipif(not fork_available(), reason="requires POSIX")

_SCENARIO = Scenario(periods=40, seed=1)


def _tournament(paths, **kw):
    kw.setdefault("isolation", "process")
    kw.setdefault("time_budget_s", 10.0)
    return run_tournament([str(p) for p in paths], _SCENARIO, metric="total_return", **kw)


# --- 1. import-time code is sandboxed like on_bar --------------------------------

@needs_process
def test_a_module_body_runs_inside_the_hardened_child(tmp_path, monkeypatch):
    """The loader used to `exec_module` in the parent before any fork, so a
    module body could write the parent's environment to disk under
    `isolation='process', harden=True`."""
    monkeypatch.setenv("ALPACA_API_KEY", "parent-key")
    out = tmp_path / "exfil.txt"
    src = algo_file(tmp_path, prelude=f"""
        import pathlib
        pathlib.Path({str(out)!r}).write_text(
            "import-time: " + ",".join(k for k in os.environ if k.startswith("ALPACA")))
        """, name="evil")

    outcome = _tournament([src], harden=True)

    assert "ALPACA" not in (out.read_text() if out.exists() else "")
    assert not any(e.ok for e in outcome.leaderboard.entries)
    failed = [e.message for e in outcome.load_errors] + [
        e.error for e in outcome.leaderboard.entries]
    assert failed, "the blocked import must surface as a failure"


@needs_process
def test_thread_isolation_still_imports_in_process(tmp_path):
    """Documented, not hidden: thread isolation trusts the code it imports."""
    src = algo_file(tmp_path, prelude="import sys\nsys._arena_seen_pid = os.getpid()")
    outcome = _tournament([src], isolation="thread")
    assert outcome.leaderboard.entries[0].ok
    assert getattr(sys, "_arena_seen_pid", None) == os.getpid()
    del sys._arena_seen_pid


# --- 2. the reply is plain data, never code ---------------------------------------

_CRAFTED = """
import pathlib, stat, sys
MARK = {mark!r}

class Boom:
    def __reduce__(self):
        return (pathlib.Path(MARK).write_text, ("ran in the parent",))

def _forge():
    # Old protocol: find the result queue up the stack and send a pickle bomb.
    f = sys._getframe()
    while f:
        q = f.f_locals.get("result_queue")
        if q is not None:
            q.put(("ok", Boom(), []))
            q.close(); q.join_thread(); os._exit(0)
        f = f.f_back
    # Any pipe protocol: write a forged, non-plain reply to every pipe we hold.
    line = b'{{"status": "ok", "equity": [{{"py/object": "Boom"}}], "index": [1]}}\\n'
    for fd in range(3, 64):
        try:
            if stat.S_ISFIFO(os.fstat(fd).st_mode):
                os.write(fd, line)
        except OSError:
            pass
    os._exit(0)
"""


@needs_process
def test_a_crafted_reply_never_runs_code_in_the_parent(tmp_path):
    mark = tmp_path / "parent_ran.txt"
    evil = algo_file(tmp_path, "_forge()", prelude=_CRAFTED.format(mark=str(mark)),
                     name="evil2")
    good = algo_file(tmp_path, name="good")

    outcome = _tournament([evil, good], harden=False)

    assert not mark.exists(), "the child's payload was unpickled in the parent"
    by = {e.name: e for e in outcome.leaderboard.entries}
    assert by["good"].ok                       # the tournament carried on
    assert by["evil2"].status == "error"


def test_the_reply_decoder_rejects_anything_but_plain_data():
    from tradebot.arena.wire import WireError, decode_result

    good = {"equity": [1.0, 2.0], "index": ["2024-01-02T00:00:00+00:00",
                                            "2024-01-03T00:00:00+00:00"],
            "trades": [], "initial_cash": 1.0, "periods_per_year": 252.0}
    assert list(decode_result(good).equity_curve) == [1.0, 2.0]
    for bad in (
        {**good, "equity": [{"py/object": "x"}, 2.0]},
        {**good, "equity": [1.0]},                         # length mismatch
        {**good, "index": [1, 2]},
        {**good, "trades": [["X", 1, 1, 1, 1, "2024-01-02", None, "long", "extra"]]},
        {**good, "trades": [{"symbol": "X"}]},
        {**good, "initial_cash": "1"},
        [1, 2],
    ):
        with pytest.raises(WireError):
            decode_result(bad)


@needs_process
def test_a_scorer_that_raises_marks_only_that_contestant_error(tmp_path):
    def broken(result):
        raise ZeroDivisionError("bad metric")

    result = run_file(SubprocessRunner(time_budget_s=10.0, harden=False),
                      algo_file(tmp_path), scorer=broken)
    assert result.status == "error"
    assert "bad metric" in result.error


# --- 3. no inherited secrets: environment, initial block, memory -----------------

def test_scrub_secrets_covers_every_dotenv_key_and_tradebot_secret():
    from tradebot.arena.sandbox import scrub_secrets
    from tradebot.credentials import DOTENV_KEYS

    env = {k: "v" for k in DOTENV_KEYS}
    env.update({"TRADEBOT_WEB_TOKEN": "link-key", "TRADEBOT_ANYTHING": "x",
                "HOME": "/tmp", "PATH": "/bin"})
    scrub_secrets(env)
    assert env == {"HOME": "/tmp", "PATH": "/bin"}


_ENV_PEEK = """
import sys

def _initial_block():
    if sys.platform.startswith("linux"):
        with open("/proc/self/environ", "rb") as fh:
            return fh.read()
    if sys.platform == "darwin":
        import ctypes
        libc = ctypes.CDLL(None)
        mib = (ctypes.c_int * 3)(1, 49, os.getpid())     # KERN_PROCARGS2
        size = ctypes.c_size_t(0)
        libc.sysctl(mib, 3, None, ctypes.byref(size), None, 0)
        buf = ctypes.create_string_buffer(size.value)
        libc.sysctl(mib, 3, buf, ctypes.byref(size), None, 0)
        return buf.raw[:size.value]
    return b""
"""


@needs_process
@pytest.mark.parametrize("harden", [False, True])
def test_the_child_cannot_see_a_parent_only_variable(tmp_path, monkeypatch, harden):
    """A forked child inherited `os.environ` (set in memory, as `.env` loading
    does) and its initial environment block; `unsetenv` clears neither."""
    monkeypatch.setenv("TRADEBOT_WEB_TOKEN", "link-signing-key")
    monkeypatch.setenv("ARENA_PARENT_ONLY", "parent-only-value")
    src = algo_file(tmp_path, """
        for key in ("TRADEBOT_WEB_TOKEN", "ARENA_PARENT_ONLY"):
            if key in os.environ:
                raise RuntimeError(key + " visible in os.environ")
            if key.encode() in _initial_block():
                raise RuntimeError(key + " visible in the initial block")
        """, prelude=_ENV_PEEK)

    entry = _tournament([src], harden=harden).leaderboard.entries[0]
    assert entry.ok, entry.error


@needs_process
def test_the_child_holds_no_parent_memory(tmp_path):
    """A fork shares the parent's heap: loaded credential objects included."""
    held = ["parentmem-" + "7f3a9c"]  # noqa: F841 - what the child must not find
    src = algo_file(tmp_path, """
        import gc
        hits = [x for o in gc.get_objects() if isinstance(o, list)
                for x in o if isinstance(x, str) and x == "parentmem-" + "7f3a9c"]
        if hits:
            raise RuntimeError("parent memory visible")
        """)
    entry = _tournament([src], harden=False).leaderboard.entries[0]
    assert entry.ok, entry.error


# --- 4. data writes: an empty working directory, Landlock where it exists ---------

@needs_process
def test_the_child_works_in_an_empty_temporary_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    src = algo_file(tmp_path, f"""
        if os.getcwd() == {str(tmp_path)!r} or os.listdir("."):
            raise RuntimeError("not in an empty directory: " + os.getcwd())
        """)
    entry = _tournament([src], harden=True).leaderboard.entries[0]
    assert entry.ok, entry.error


@needs_process
def test_the_report_names_the_tier_honestly():
    r, w = os.pipe()
    pid = os.fork()
    if pid == 0:  # child
        import json

        from tradebot.arena.sandbox import apply_hardening
        os.close(r)
        report = apply_hardening(isolate_network=False)
        os.write(w, json.dumps(sorted(report)).encode())
        os._exit(0)
    os.close(w)
    keys = __import__("json").loads(os.read(r, 4096))
    os.waitpid(pid, 0)
    assert "no_data_writes" in keys and "no_write" not in keys
    assert "read_only_fs" in keys        # Landlock: reported even where refused


def _landlock_abi() -> int:
    from tradebot.arena.landlock import landlock_abi

    return landlock_abi()


@needs_process
@pytest.mark.skipif(not sys.platform.startswith("linux"),
                    reason="Landlock is Linux-only; on macOS a hardened child can "
                           "still truncate or unlink files its user owns")
def test_a_hardened_child_cannot_truncate_or_unlink_outside_its_directory(tmp_path):
    if _landlock_abi() < 1:
        pytest.skip("this kernel does not enforce Landlock")
    victim = tmp_path / "victim.db"
    victim.write_text("x" * 1000)
    src = algo_file(tmp_path, f"""
        errors = []
        try:
            open({str(victim)!r}, "w").close()
        except OSError as exc:
            errors.append("truncate")
        try:
            os.remove({str(victim)!r})
        except OSError as exc:
            errors.append("unlink")
        if errors != ["truncate", "unlink"]:
            raise RuntimeError("allowed: " + repr(errors))
        """)
    entry = _tournament([src], harden=True).leaderboard.entries[0]
    assert entry.ok, entry.error
    assert victim.read_text() == "x" * 1000


# --- 14. a child that dies early is an error, at once ---------------------------

@needs_process
def test_a_child_that_dies_before_replying_is_an_error_not_a_timeout(tmp_path):
    start = time.perf_counter()
    result = run_file(SubprocessRunner(time_budget_s=20.0, harden=False),
                      algo_file(tmp_path, "os._exit(1)"))
    assert result.status == "error"
    assert "exit" in result.error
    assert time.perf_counter() - start < 10.0      # not the 20 s budget


@needs_process
def test_a_relative_path_still_loads_in_the_childs_own_directory(tmp_path, monkeypatch):
    algo_file(tmp_path, name="rel")
    monkeypatch.chdir(tmp_path)
    outcome = _tournament(["rel.py"], harden=False)
    assert not outcome.load_errors
    entry = outcome.leaderboard.entries[0]
    assert entry.ok and entry.contestant.source == "rel.py"
