import json
import os

import logging

import pytest

from tradebot.arena.contestant import Contestant
from tradebot.arena.interfaces import Action, Algo
from tradebot.arena.runner import SubprocessRunner, default_runner, fork_available
from tradebot.arena.scoring import get_scorer
from tradebot.arena.simulation import SimConfig
from tradebot.data.synthetic import synthetic_ohlcv
from tradebot.risk import RiskConfig, RiskManager

from .arena_files import algo_file, run_file

from tradebot.arena.sandbox import seccomp_available

needs_fork = pytest.mark.skipif(not fork_available(), reason="requires fork")
needs_seccomp = pytest.mark.skipif(
    not (fork_available() and seccomp_available()),
    reason="requires fork + libseccomp",
)


# --- direct hardening checks (in a forked child) -----------------------------

@needs_fork
def test_apply_hardening_blocks_disk_writes(tmp_path):
    target = str(tmp_path / "evil.txt")
    pid = os.fork()
    if pid == 0:  # child
        from tradebot.arena.sandbox import apply_hardening
        apply_hardening()
        try:
            with open(target, "w") as f:
                f.write("x" * 1000)
                f.flush()
            os._exit(0)        # write succeeded -> NOT blocked
        except OSError:
            os._exit(42)       # blocked
    _, status = os.waitpid(pid, 0)
    code = os.waitstatus_to_exitcode(status)
    assert code in (42, -25)   # OSError, or killed by SIGXFSZ(25)


@needs_fork
def test_apply_hardening_isolates_network(tmp_path):
    r, w = os.pipe()
    pid = os.fork()
    if pid == 0:  # child
        os.close(r)
        import socket

        from tradebot.arena.sandbox import apply_hardening
        report = apply_hardening()
        ifaces = [name for _, name in socket.if_nameindex()]
        os.write(w, json.dumps({"net": report.get("network"), "ifaces": ifaces}).encode())
        os._exit(0)
    os.close(w)
    data = os.read(r, 4096)
    os.waitpid(pid, 0)
    result = json.loads(data)
    if result["net"]:                       # network isolation was enforced
        assert set(result["ifaces"]) <= {"lo"}   # only (down) loopback remains


# --- runner integration ------------------------------------------------------
# Process-isolated contestants are imported in a fresh interpreter, so they
# live in files (`tests/arena_files.py`).

def _run(tmp_path, body, harden, seccomp=False):
    runner = SubprocessRunner(time_budget_s=10.0, harden=harden, seccomp=seccomp)
    return run_file(runner, algo_file(tmp_path, body))


@needs_fork
def test_hardened_runner_still_runs_a_normal_contestant(tmp_path):
    # Sandboxing must not break a compute-only algo (result returns via the pipe).
    assert _run(tmp_path, "pass", harden=True).status == "ok"


@needs_fork
def test_hardened_runner_blocks_a_disk_writing_contestant(tmp_path):
    target = str(tmp_path / "out.txt")
    body = f"""
        with open({target!r}, "w") as f:
            f.write("x" * 1000)
            f.flush()
        """
    assert _run(tmp_path, body, harden=True).status != "ok"      # write blocked -> not ok
    assert _run(tmp_path, body, harden=False).status == "ok"     # allowed when not hardened


@needs_fork
def test_default_runner_hardens_by_default():
    assert default_runner(isolation="process").harden is True       # on by default
    assert default_runner(isolation="process", harden=False).harden is False


# --- seccomp tier ------------------------------------------------------------

@needs_seccomp
def test_apply_seccomp_blocks_execve(tmp_path):
    """A direct exec attempt must fail with EPERM once the filter is loaded."""
    pid = os.fork()
    if pid == 0:  # child
        from tradebot.arena.sandbox import apply_hardening
        report = apply_hardening(seccomp=True)
        if not report.get("seccomp"):
            os._exit(7)            # filter didn't load -> distinguish from a pass
        try:
            os.execv("/bin/true", ["/bin/true"])
            os._exit(0)            # exec succeeded -> NOT blocked
        except OSError:
            os._exit(42)           # blocked (EPERM)
    _, status = os.waitpid(pid, 0)
    assert os.waitstatus_to_exitcode(status) == 42


_SPAWN = """
    import subprocess
    subprocess.run(["/bin/true"], check=True)   # needs execve -> blocked
    """


@needs_seccomp
def test_seccomp_runner_blocks_a_spawning_contestant(tmp_path):
    # Under seccomp a contestant that shells out can't exec -> run fails, not ok.
    assert _run(tmp_path, _SPAWN, harden=True, seccomp=True).status != "ok"


@needs_seccomp
def test_seccomp_runner_still_runs_a_normal_contestant(tmp_path):
    # The filter must leave an ordinary numeric contestant (and the reply
    # pipe) untouched.
    assert _run(tmp_path, "pass", harden=True, seccomp=True).status == "ok"


@needs_fork
def test_default_runner_seccomp_is_opt_in():
    assert default_runner(isolation="process").seccomp is False        # off by default
    assert default_runner(isolation="process", seccomp=True).seccomp is True


# --- unavailable containment: reported, not fatal ------------------------------

def _run_with(runner, tmp_path):
    return run_file(runner, algo_file(tmp_path))


def _unenforceable(runner, mechanism="network"):
    """Pretend the kernel refuses one containment mechanism.

    The child is a fresh interpreter, so a monkeypatch here cannot reach it;
    the runner carries the pretence into the child's report instead.
    """
    runner._pretend_unenforced = (mechanism,)
    return runner


@needs_fork
def test_containment_the_kernel_refuses_is_reported_but_still_runs(tmp_path, caplog):
    """A kernel that will not grant a network namespace is a portability fact,
    not a threat. CI runners, unprivileged containers and macOS all refuse it.

    Refusing to run there made the arena unusable and turned CI red on every
    commit while every contestant reported 'SandboxError'. "Never silently
    downgrade" is satisfied by saying so, loudly — not by refusing.
    """
    runner = _unenforceable(SubprocessRunner(time_budget_s=10.0, harden=True))

    with caplog.at_level(logging.WARNING, logger="tradebot.arena.runner"):
        result = _run_with(runner, tmp_path)

    assert result.ok                              # it ran
    assert "could NOT be enforced" in caplog.text  # and it said so
    assert "network" in caplog.text


@needs_fork
def test_require_sandbox_turns_missing_containment_into_a_failure(tmp_path):
    """For anyone whose threat model actually needs the guarantee."""
    runner = _unenforceable(SubprocessRunner(time_budget_s=10.0, harden=True,
                                             require_sandbox=True))

    result = _run_with(runner, tmp_path)
    assert not result.ok
    assert "SandboxError" in (result.error or "")
    assert "network" in (result.error or "")


@needs_fork
def test_the_degradation_warning_is_emitted_once_per_mechanism(tmp_path, caplog):
    """Twelve identical warnings per tournament would train everyone to ignore it."""
    runner = _unenforceable(SubprocessRunner(time_budget_s=10.0, harden=True))

    with caplog.at_level(logging.WARNING, logger="tradebot.arena.runner"):
        _run_with(runner, tmp_path)
        _run_with(runner, tmp_path)
        _run_with(runner, tmp_path)

    # Once per mechanism, not once per run. The faked refusal is always among
    # them; the host may genuinely refuse others too (macOS has no `prctl` or
    # Landlock, so `no_new_privs` and `read_only_fs` degrade there), and each
    # of those warns once as well.
    assert "network" in runner.degraded
    assert caplog.text.count("could NOT be enforced") == len(runner.degraded)


def test_a_missing_libc_symbol_is_reported_not_raised(monkeypatch):
    """`prctl`/`unshare` do not exist on macOS. The lookup used to raise inside
    the forked child, killing it before it could report, so every hardened
    contestant came back as a bare TIMEOUT instead of a degradation warning."""
    import tradebot.arena.sandbox as sandbox_mod

    monkeypatch.setattr(sandbox_mod, "_libc", lambda: object())  # no symbols at all
    # Only the libc-backed mechanisms: the rlimit ones would cap this process.
    report = sandbox_mod.apply_hardening(no_write=False, max_open_files=0)
    assert report == {"no_new_privs": False, "network": False}


# --- the child never sees broker secrets -------------------------------------

def test_scrub_secrets_removes_broker_keys_and_the_live_latch():
    from tradebot.arena.sandbox import scrub_secrets

    env = {"ALPACA_API_KEY": "k", "ALPACA_API_SECRET": "s", "ALPACA_DATA_FEED": "iex",
           "TRADEBOT_LIVE_CONFIRM": "I_UNDERSTAND", "TRADEBOT_WEB_TOKEN": "t",
           "HOME": "/tmp", "PATH": "/bin"}
    removed = scrub_secrets(env)
    assert removed == ["ALPACA_API_KEY", "ALPACA_API_SECRET", "ALPACA_DATA_FEED",
                       "TRADEBOT_LIVE_CONFIRM", "TRADEBOT_WEB_TOKEN"]
    assert env == {"HOME": "/tmp", "PATH": "/bin"}


@needs_fork
def test_isolated_contestant_cannot_read_broker_keys(monkeypatch, tmp_path):
    monkeypatch.setenv("ALPACA_API_KEY", "leak-me")
    monkeypatch.setenv("TRADEBOT_LIVE_CONFIRM", "I_UNDERSTAND")
    body = """
        if "ALPACA_API_KEY" in os.environ or "TRADEBOT_LIVE_CONFIRM" in os.environ:
            raise RuntimeError("secret visible in the sandbox")
        """
    result = _run(tmp_path, body, harden=False)
    assert result.status == "ok", result.error
