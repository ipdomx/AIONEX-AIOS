"""Native, offline build-process regressions. No production or provider actions."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "web-dashboard/backend/scripts"
sys.path.insert(0, str(SCRIPTS))
try:
    spec = importlib.util.spec_from_file_location("trivy_process_lifecycle_target", SCRIPTS / "build_trivy.py")
    assert spec and spec.loader
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
finally:
    sys.path.pop(0)


def receipt(log: Path):
    return json.loads(log.with_name(log.name + ".execution.json").read_text())


def await_file(path: Path, seconds: float = 2) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if path.exists():
            return True
        time.sleep(0.01)
    return path.exists()


@pytest.mark.parametrize("depth", [1, 2])
def test_timeout_prevents_descendant_work_after_return(tmp_path, monkeypatch, depth):
    # The leaf is deliberately finite even against the broken implementation.
    # A release barrier, not a sleep race, makes post-timeout work observable.
    ready, release, late = [tmp_path / name for name in ("ready.json", "release", "late-write")]
    leaf = (
        "import json,os,time; from pathlib import Path; "
        f"Path({str(ready)!r}).write_text(json.dumps({{'pid':os.getpid(),'group':os.getpgrp()}})); "
        "deadline=time.monotonic()+4\n"
        f"while not Path({str(release)!r}).exists() and time.monotonic()<deadline: time.sleep(0.01)\n"
        f"if Path({str(release)!r}).exists(): Path({str(late)!r}).write_text('SYNTHETIC_LATE_BUILD_EFFECT')\n"
    )
    driver = leaf
    for _ in range(depth):
        driver = (
            "import subprocess,sys; "
            f"child=subprocess.Popen([sys.executable,'-c',{driver!r}]); "
            "child.wait(timeout=6)"
        )
    monkeypatch.setattr(m, "COLD_COMMAND_TIMEOUT_SECONDS", 1.0)
    log = tmp_path / "build.log"
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            m.run_cold_build_step([sys.executable, "-c", driver], tmp_path,
                                  {"PATH": os.defpath, "PYTHONUNBUFFERED": "1"}, log)
        assert ready.is_file(), "Fixture never started: this cannot prove descendant cleanup"
        release.write_text("release only after timeout returned")
        assert not await_file(late, 0.7), "Build descendant continued work after outer timeout returned"
        assert receipt(log)["status"] == "TIMED_OUT"
    finally:
        release.touch(exist_ok=True)
        # Finite fixture exits on release even when baseline assertions fail.
        time.sleep(0.05)


@pytest.mark.parametrize("value", [0, -1, float("inf"), float("nan"), True])
def test_invalid_deadline_is_rejected_before_any_process(tmp_path, monkeypatch, value):
    monkeypatch.setattr(m.subprocess, "Popen", lambda *a, **kw: pytest.fail("must not launch"))
    with pytest.raises(ValueError):
        m.run_cold_process(["not-launched"], tmp_path, {}, tmp_path / "log", value)
    assert not (tmp_path / "log").exists()


def test_real_success_uses_private_group_and_reaps_only_after_signal(tmp_path, monkeypatch):
    real_killpg = os.killpg
    observations = []
    def observe_signal(pgid, sig):
        # A waitable leader still reserves this numeric ID when it is signaled.
        state = os.waitid(os.P_PID, pgid, os.WEXITED | os.WNOWAIT | os.WNOHANG)
        assert state is not None and state.si_pid == pgid
        assert os.getpgid(pgid) == pgid and pgid != os.getpgrp()
        observations.append((pgid, sig))
        real_killpg(pgid, sig)
    monkeypatch.setattr(m.os, "killpg", observe_signal)
    log = tmp_path / "success.log"
    m.run_cold_build_step([sys.executable, "-c", "print('VALID_BUILD_OUTPUT')"],
                          tmp_path, {"PATH": os.defpath}, log)
    assert log.read_text() == "VALID_BUILD_OUTPUT\n" and receipt(log)["status"] == "PASSED"
    assert len(observations) == 1 and observations[0][1] == m.signal.SIGKILL
    with pytest.raises(ChildProcessError):
        os.waitid(os.P_PID, observations[0][0], os.WEXITED | os.WNOHANG)


@pytest.mark.parametrize("exit_code", [0, 7])
def test_exited_driver_does_not_leave_owned_descendant_work(tmp_path, exit_code):
    ready, release, late = [tmp_path / name for name in ("ready", "release", "late")]
    leaf = (
        "import time; from pathlib import Path; "
        f"Path({str(ready)!r}).touch(); end=time.monotonic()+4\n"
        f"while not Path({str(release)!r}).exists() and time.monotonic()<end: time.sleep(0.01)\n"
        f"if Path({str(release)!r}).exists(): Path({str(late)!r}).touch()\n"
    )
    driver = (
        "import subprocess,sys,time; from pathlib import Path; "
        f"subprocess.Popen([sys.executable,'-c',{leaf!r}]); end=time.monotonic()+3\n"
        f"while not Path({str(ready)!r}).exists() and time.monotonic()<end: time.sleep(0.01)\n"
        f"raise SystemExit({exit_code})\n"
    )
    log = tmp_path / "driver.log"
    try:
        if exit_code:
            with pytest.raises(RuntimeError):
                m.run_cold_build_step([sys.executable, "-c", driver], tmp_path, {"PATH": os.defpath}, log)
        else:
            m.run_cold_build_step([sys.executable, "-c", driver], tmp_path, {"PATH": os.defpath}, log)
        assert ready.is_file(), "Fixture did not start"
        release.touch()
        assert not await_file(late, 0.5)
        assert receipt(log)["status"] == ("FAILED" if exit_code else "PASSED")
    finally:
        release.touch(exist_ok=True)


@pytest.mark.parametrize("failure", [KeyboardInterrupt("synthetic interrupt"), RuntimeError("synthetic waiter failure")])
def test_caught_supervisor_interruption_stops_owned_child(tmp_path, monkeypatch, failure):
    ready, release, late = [tmp_path / name for name in ("ready", "release", "late")]
    script = (
        "import time; from pathlib import Path; "
        f"Path({str(ready)!r}).touch(); end=time.monotonic()+4\n"
        f"while not Path({str(release)!r}).exists() and time.monotonic()<end: time.sleep(0.01)\n"
        f"if Path({str(release)!r}).exists(): Path({str(late)!r}).touch()\n"
    )
    def interrupt(pid, args, timeout):
        assert await_file(ready), "Fixture did not start"
        raise failure
    monkeypatch.setattr(m, "wait_cold_leader", interrupt)
    log = tmp_path / "interrupt.log"
    try:
        with pytest.raises(type(failure)) as error:
            m.run_cold_build_step([sys.executable, "-c", script], tmp_path, {"PATH": os.defpath}, log)
        assert error.value is failure and receipt(log)["status"] == "FAILED"
        release.touch()
        assert not await_file(late, 0.5)
    finally:
        release.touch(exist_ok=True)


def test_timeout_does_not_signal_unrelated_sibling(tmp_path, monkeypatch):
    ready, release, completed = [tmp_path / name for name in ("sibling-ready", "release", "completed")]
    sibling_script = (
        "import time; from pathlib import Path; "
        f"Path({str(ready)!r}).touch(); end=time.monotonic()+5\n"
        f"while not Path({str(release)!r}).exists() and time.monotonic()<end: time.sleep(0.01)\n"
        f"if Path({str(release)!r}).exists(): Path({str(completed)!r}).touch()\n"
    )
    sibling = subprocess.Popen([sys.executable, "-c", sibling_script], env={"PATH": os.defpath})
    try:
        assert await_file(ready)
        monkeypatch.setattr(m, "COLD_COMMAND_TIMEOUT_SECONDS", 0.2)
        with pytest.raises(subprocess.TimeoutExpired):
            m.run_cold_build_step([sys.executable, "-c", "import time; time.sleep(3)"],
                                  tmp_path, {"PATH": os.defpath}, tmp_path / "timeout.log")
        assert sibling.poll() is None
        release.touch()
        assert sibling.wait(timeout=2) == 0 and completed.exists()
    finally:
        release.touch(exist_ok=True)
        if sibling.poll() is None:
            sibling.terminate()
        sibling.wait(timeout=2)


@pytest.mark.parametrize("lost_ownership", [False, True])
def test_unknown_or_failed_cleanup_never_passes(tmp_path, monkeypatch, lost_ownership):
    calls = []
    class FakeProcess:
        pid = 987654
        returncode = 0
        def wait(self, timeout):
            calls.append(("wait", timeout))
            return 0
    monkeypatch.setattr(m.subprocess, "Popen", lambda *a, **kw: FakeProcess())
    def observe(pid, args, timeout):
        if lost_ownership:
            raise ChildProcessError("synthetic foreign reaper")
    def signal_group(pgid, signum):
        calls.append(("signal", pgid))
        raise PermissionError("synthetic signal denial")
    monkeypatch.setattr(m, "wait_cold_leader", observe)
    monkeypatch.setattr(m.os, "killpg", signal_group)
    log = tmp_path / "uncertain.log"
    with pytest.raises(RuntimeError if lost_ownership else PermissionError):
        m.run_cold_build_step(["synthetic-only"], tmp_path, {}, log)
    assert receipt(log)["status"] == "FAILED"
    assert calls == ([] if lost_ownership else [("signal", 987654), ("wait", 10)])


def test_incompatible_child_reaping_policy_rejected_before_spawn(tmp_path, monkeypatch):
    monkeypatch.setattr(m.signal, "getsignal", lambda signum: m.signal.SIG_IGN)
    monkeypatch.setattr(m.subprocess, "Popen", lambda *a, **kw: pytest.fail("must not launch"))
    with pytest.raises(RuntimeError, match="child-reaping"):
        m.run_cold_process(["not-launched"], tmp_path, {}, tmp_path / "log", 1)
    assert not (tmp_path / "log").exists()
