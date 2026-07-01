import json
import os

import pytest

from tradebot.arena.contestant import Contestant
from tradebot.arena.interfaces import Action, Algo
from tradebot.arena.runner import SubprocessRunner, default_runner, fork_available
from tradebot.arena.scoring import get_scorer
from tradebot.arena.simulation import SimConfig
from tradebot.data.synthetic import synthetic_ohlcv
from tradebot.risk import RiskConfig, RiskManager

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

def _run(factory, harden, seccomp=False):
    df = synthetic_ohlcv(periods=40, seed=1)
    runner = SubprocessRunner(time_budget_s=5.0, harden=harden, seccomp=seccomp)
    contestant = Contestant(name="x", factory=factory, kind="event")
    return runner.run(contestant, {"DEMO": df}, RiskManager(RiskConfig()),
                      SimConfig(), get_scorer("total_return"))


class _FlatAlgo(Algo):
    def on_bar(self, bar, ctx):
        return Action.flat()


@needs_fork
def test_hardened_runner_still_runs_a_normal_contestant():
    # Sandboxing must not break a compute-only algo (result returns via the pipe).
    assert _run(_FlatAlgo, harden=True).status == "ok"


@needs_fork
def test_hardened_runner_blocks_a_disk_writing_contestant(tmp_path):
    target = str(tmp_path / "out.txt")

    class _Writer(Algo):
        def on_bar(self, bar, ctx):
            with open(target, "w") as f:
                f.write("x" * 1000)
                f.flush()
            return Action.flat()

    assert _run(_Writer, harden=True).status != "ok"      # write blocked -> not ok
    assert _run(_Writer, harden=False).status == "ok"     # allowed when not hardened


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


class _Spawner(Algo):
    def on_bar(self, bar, ctx):
        import subprocess
        subprocess.run(["/bin/true"], check=True)   # needs execve -> blocked
        return Action.flat()


@needs_seccomp
def test_seccomp_runner_blocks_a_spawning_contestant():
    # Under seccomp a contestant that shells out can't exec -> run fails, not ok.
    assert _run(_Spawner, harden=True, seccomp=True).status != "ok"


@needs_seccomp
def test_seccomp_runner_still_runs_a_normal_contestant():
    # The filter must leave an ordinary numeric contestant (and the result pipe,
    # which forks a feeder thread via clone) untouched.
    assert _run(_FlatAlgo, harden=True, seccomp=True).status == "ok"


@needs_fork
def test_default_runner_seccomp_is_opt_in():
    assert default_runner(isolation="process").seccomp is False        # off by default
    assert default_runner(isolation="process", seccomp=True).seccomp is True
