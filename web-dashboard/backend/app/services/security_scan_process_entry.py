"""Private Linux child supervisor for fixed, authorized scanner adapters.

The parent persists ownership before releasing stdin. This single-threaded
subreaper adopts orphaned descendants (including setsid/double-fork children),
terminates only its own unreaped children and reports ECHILD on a private pipe.
Scanner stdout is never treated as cleanup evidence. No HTTP command interface.
"""
from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import time


def main() -> int:
    if len(sys.argv) < 3 or not sys.platform.startswith("linux"):
        return 125
    proof_fd = int(sys.argv[1])
    os.set_blocking(proof_fd, True)
    stopping = False

    def stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    # waitpid owns all reaping in this single-threaded process; SIGCHLD must
    # not be ignored, which could manufacture an ECHILD without waiting.
    signal.signal(signal.SIGCHLD, signal.SIG_DFL)
    parent = os.getppid()
    libc = ctypes.CDLL(None, use_errno=True)
    prctl = libc.prctl
    prctl.restype = ctypes.c_int
    prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
    if prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
        return 125
    if prctl(1, signal.SIGTERM, 0, 0, 0) != 0:  # PR_SET_PDEATHSIG
        return 125
    if os.getppid() != parent:
        stopping = True
    os.write(proof_fd, b"READY\n")
    released = False
    while not stopping:
        ready, _, _ = select.select([0], [], [], 0.05)
        if ready:
            released = os.read(0, 1) == b"1"
            break
        if os.getppid() != parent:
            stopping = True
    child: subprocess.Popen[bytes] | None = None
    exit_code = 125
    if released and not stopping:
        # No proof descriptor is inherited by the adapter. Commands are supplied
        # exclusively by the fixed scanner adapter, without shell expansion.
        child = subprocess.Popen(sys.argv[2:], stdin=subprocess.DEVNULL, close_fds=True)
    leader_done = child is None
    while True:
        no_children = False
        while True:
            try:
                pid, status = os.waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                no_children = True
                break
            if pid == 0:
                break
            if child is not None and pid == child.pid:
                exit_code = os.waitstatus_to_exitcode(status)
                child.returncode = exit_code
                leader_done = True
        if no_children:
            if not leader_done:
                return 125  # Missing leader status is not cleanup proof.
            break
        if leader_done or stopping or os.getppid() != parent:
            stopping = True
            # These are direct unreaped children, not a global PID/session scan.
            # No other thread or handler reaps them, so their PID cannot be
            # recycled between this inventory and kill. Killing a parent adopts
            # its children on the next iteration, even across session changes.
            children = Path(f"/proc/self/task/{os.getpid()}/children").read_text().split()
            for raw in children:
                pid = int(raw)
                if pid <= 1:
                    raise RuntimeError("Invalid owned child identity")
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        time.sleep(0.01)
    proof = {"version": 1, "subreaper": True, "children_reaped": True,
             "exit_code": exit_code, "started": child is not None}
    os.write(proof_fd, json.dumps(proof, separators=(",", ":")).encode() + b"\n")
    os.close(proof_fd)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
