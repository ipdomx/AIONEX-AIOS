#!/usr/bin/env python3
"""Fail-closed, journaled final graceful stop for FR-06 maintenance.

This operator targets exactly three production services:
- telegram-worker
- user-telegram-worker
- operations-observer

It requires the same closed schema-8 host-maintenance authority for every
observation and before every first-and-only SIGTERM.  It never sends SIGKILL,
never sends a second signal for an unresolved intent, never restarts a service,
and never claims full-host closure.  A later invocation may only reconcile an
already-stopped exact container epoch; a still-running unresolved intent halts.

An optional prior control-block receipt may be bound into a new journal only
when it proves that an earlier attempted signal was blocked before execution.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import UUID

ROOT = Path("/opt/AIOS")
JOURNAL_BASE = Path("/var/lib/aionex/fr06-final-maintenance")
TARGETS = (
    ("telegram-worker", "web-dashboard-telegram-worker-1"),
    ("user-telegram-worker", "web-dashboard-user-telegram-worker-1"),
    ("operations-observer", "web-dashboard-operations-observer-1"),
)
SCHEMA = "aionex.fr06-final-graceful-stop-operator.v1"
BLOCK_SCHEMA = "aionex.fr06-graceful-stop-control-block.v1"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.security.fr06c5d11_graceful_stop_acceptance import accept

AUTHORITY_READER = r'''import asyncio,json
from app.db.base import SessionLocal
from app.services.host_maintenance_admission import read_admission_snapshot
async def main():
 async with SessionLocal() as s:
  x=await read_admission_snapshot(s,required_scope="realtime_media_requests")
  print(json.dumps({"schema_version":x.schema_version,"operation_id":x.operation_id,
   "generation":x.generation,"status":x.status,"enabled":x.enabled,
   "full_host_closure":x.full_host_closure}))
asyncio.run(main())'''

class GracefulStopHalted(RuntimeError):
    """The operator refuses to continue without replaying an uncertain effect."""


def _uuid(value: Any) -> bool:
    try:
        return isinstance(value, str) and str(UUID(value)) == value
    except ValueError:
        return False


def _canon(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def _run(args: list[str], *, timeout: int = 20) -> str:
    result = subprocess.run(args, text=True, capture_output=True, timeout=timeout, check=False)
    if result.returncode:
        raise GracefulStopHalted("fixed operator command failed; no retry performed")
    return result.stdout.strip()


def _safe_root(path: Path) -> int:
    resolved = path.resolve(strict=False)
    base = JOURNAL_BASE.resolve()
    if resolved == base or base not in resolved.parents:
        raise GracefulStopHalted("journal root must be an operation-private child")
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    st = os.lstat(path)
    if (
        not stat.S_ISDIR(st.st_mode)
        or stat.S_IMODE(st.st_mode) != 0o700
        or st.st_uid != os.geteuid()
    ):
        raise GracefulStopHalted("private root-owned 0700 journal required")
    return os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW)


def _write_new(root_fd: int, name: str, value: Any) -> None:
    data = _canon(value)
    fd = os.open(
        name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
        0o600,
        dir_fd=root_fd,
    )
    try:
        total = 0
        while total < len(data):
            total += os.write(fd, data[total:])
        os.fsync(fd)
    finally:
        os.close(fd)
    os.fsync(root_fd)


def _read(root_fd: int, name: str) -> Any:
    fd = os.open(name, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW, dir_fd=root_fd)
    try:
        st = os.fstat(fd)
        if (
            not stat.S_ISREG(st.st_mode)
            or stat.S_IMODE(st.st_mode) != 0o600
            or st.st_uid != os.geteuid()
            or st.st_nlink != 1
            or st.st_size > 1024 * 1024
        ):
            raise GracefulStopHalted("unsafe journal record")
        raw = os.read(fd, st.st_size + 1)
        if len(raw) != st.st_size or not raw.endswith(b"\n"):
            raise GracefulStopHalted("incomplete journal record")
        return json.loads(raw)
    finally:
        os.close(fd)


def _exists(root_fd: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=root_fd, follow_symlinks=False)
        return True
    except FileNotFoundError:
        return False


def _authority(operation_id: str, generation: int) -> dict[str, Any]:
    raw = _run(
        [
            "docker",
            "exec",
            "web-dashboard-backend-1",
            "/opt/venv/bin/python",
            "-c",
            AUTHORITY_READER,
        ],
        timeout=20,
    )
    value = json.loads(raw)
    expected = {
        "schema_version": 8,
        "operation_id": operation_id,
        "generation": generation,
        "status": "closed",
        "enabled": False,
        "full_host_closure": False,
    }
    if value != expected:
        raise GracefulStopHalted("closed maintenance authority changed")
    return {
        "operation_id": operation_id,
        "generation": generation,
        "status": "closed",
        "enabled": False,
        "full_host_closure": False,
    }


def _inspect(service: str, name: str) -> dict[str, Any]:
    rows = json.loads(_run(["docker", "inspect", name]))
    if not isinstance(rows, list) or len(rows) != 1:
        raise GracefulStopHalted("target identity unavailable")
    row = rows[0]
    labels = row.get("Config", {}).get("Labels", {})
    state = row.get("State", {})
    policy = row.get("HostConfig", {}).get("RestartPolicy", {})
    if (
        row.get("Name") != "/" + name
        or labels.get("com.docker.compose.project") != "web-dashboard"
        or labels.get("com.docker.compose.service") != service
        or labels.get("com.docker.compose.oneoff", "False").lower() == "true"
        or policy.get("Name") != "no"
        or policy.get("MaximumRetryCount", 0) != 0
        or type(row.get("RestartCount")) is not int
        or row["RestartCount"] < 0
        or not isinstance(row.get("Id"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", row["Id"])
        or not isinstance(row.get("Image"), str)
    ):
        raise GracefulStopHalted("target identity/restart contract differs")
    health = state.get("Health", {}).get("Status")
    if state.get("Running") is True and health not in (None, "healthy"):
        raise GracefulStopHalted("running target is not healthy")
    return row


def _before(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "container_id": row["Id"],
        "image": row["Image"],
        "restart_count": row["RestartCount"],
        "running": row["State"]["Running"],
        "restart_policy": "no",
    }


def _accept_before(row: dict[str, Any], expected: dict[str, Any]) -> None:
    if _before(row) != expected or row["State"].get("Running") is not True:
        raise GracefulStopHalted("running target epoch changed")


def _stopped_cleanly(row: dict[str, Any], expected: dict[str, Any]) -> bool:
    return (
        row["Id"] == expected["container_id"]
        and row["Image"] == expected["image"]
        and row["RestartCount"] == expected["restart_count"]
        and row["State"].get("Running") is False
        and row["State"].get("ExitCode") == 0
        and row["State"].get("OOMKilled") is False
        and row.get("HostConfig", {}).get("RestartPolicy", {}).get("Name") == "no"
    )


def _after(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "container_id": row["Id"],
        "restart_count": row["RestartCount"],
        "running": row["State"]["Running"],
        "restart_policy": "no",
        "exit_code": row["State"]["ExitCode"],
    }


def _blocked_receipt(path: Path | None, operation_id: str, generation: int) -> dict[str, Any] | None:
    if path is None:
        return None
    raw = path.read_bytes()
    value = json.loads(raw)
    if (
        value.get("schema") != BLOCK_SCHEMA
        or value.get("operation_id") != operation_id
        or value.get("generation") != generation
        or value.get("intended_signal") != "SIGTERM"
        or value.get("effect_executed") is not False
        or value.get("automatic_retry") is not False
        or value.get("graceful_stop_verified") is not False
        or value.get("full_host_closure") is not False
        or value.get("production_activation_authorized") is not False
    ):
        raise GracefulStopHalted("prior block receipt does not prove a no-effect attempt")
    return {
        "sha256": hashlib.sha256(raw).hexdigest(),
        "attempted_target": value.get("attempted_target"),
        "effect_executed": False,
    }


def _source_identity() -> dict[str, str]:
    script = Path(__file__).resolve()
    head = _run(["git", "-C", str(ROOT), "rev-parse", "HEAD"])
    if _run(["git", "-C", str(ROOT), "status", "--porcelain"]):
        raise GracefulStopHalted("server source is not clean")
    return {
        "source_commit": head,
        "operator_sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
    }


def execute(
    *,
    operation_id: str,
    generation: int,
    journal_root: Path,
    prior_block: Path | None = None,
) -> dict[str, Any]:
    if not _uuid(operation_id) or type(generation) is not int or generation < 8:
        raise GracefulStopHalted("valid maintenance authority identity required")

    root_fd = _safe_root(journal_root)
    try:
        authority = _authority(operation_id, generation)
        blocked = _blocked_receipt(prior_block, operation_id, generation)
        source = _source_identity()

        if not _exists(root_fd, "session-intent.json"):
            baseline: dict[str, Any] = {}
            for service, name in TARGETS:
                row = _inspect(service, name)
                if row["State"].get("Running") is not True:
                    raise GracefulStopHalted("all targets must be running before the first journal")
                baseline[service] = _before(row)
            session = {
                "schema": SCHEMA,
                "operation_id": operation_id,
                "generation": generation,
                "services": [service for service, _ in TARGETS],
                "signal": "SIGTERM",
                "force_permitted": False,
                "automatic_retry": False,
                "authority": authority,
                "source": source,
                "prior_no_effect_block": blocked,
                "baseline": baseline,
            }
            _write_new(root_fd, "session-intent.json", session)
        else:
            session = _read(root_fd, "session-intent.json")
            if (
                session.get("schema") != SCHEMA
                or session.get("operation_id") != operation_id
                or session.get("generation") != generation
                or session.get("services") != [service for service, _ in TARGETS]
                or session.get("authority") != authority
                or session.get("source") != source
                or session.get("prior_no_effect_block") != blocked
            ):
                raise GracefulStopHalted("existing graceful-stop session differs")

        baseline = session["baseline"]
        before = {
            "authority": authority,
            "services": {
                service: {
                    "container_id": baseline[service]["container_id"],
                    "restart_count": baseline[service]["restart_count"],
                    "running": True,
                    "restart_policy": "no",
                }
                for service, _ in TARGETS
            },
        }

        for service, name in TARGETS:
            intent_name = f"{service}-signal-intent.json"
            accepted_name = f"{service}-stop-accepted.json"
            expected = baseline[service]
            row = _inspect(service, name)

            if _exists(root_fd, accepted_name):
                accepted = _read(root_fd, accepted_name)
                if not _stopped_cleanly(row, expected) or accepted.get("container_id") != expected["container_id"]:
                    raise GracefulStopHalted("accepted stop no longer matches exact target epoch")
                continue

            if _exists(root_fd, intent_name):
                if _stopped_cleanly(row, expected):
                    _write_new(
                        root_fd,
                        accepted_name,
                        {
                            "operation_id": operation_id,
                            "generation": generation,
                            "service": service,
                            "container_id": expected["container_id"],
                            "image": expected["image"],
                            "restart_count": expected["restart_count"],
                            "signal": "SIGTERM",
                            "exit_code": 0,
                            "forced_kill": False,
                            "replayed_signal": False,
                            "reconciled_after_intent": True,
                        },
                    )
                    continue
                if row["State"].get("Running") is True:
                    raise GracefulStopHalted(
                        "unresolved prior signal intent while target still runs; refusing replay"
                    )
                raise GracefulStopHalted("target stopped ambiguously after signal intent")

            _accept_before(row, expected)
            _authority(operation_id, generation)
            _write_new(
                root_fd,
                intent_name,
                {
                    "operation_id": operation_id,
                    "generation": generation,
                    "service": service,
                    "container_id": expected["container_id"],
                    "image": expected["image"],
                    "restart_count": expected["restart_count"],
                    "signal": "SIGTERM",
                    "force_permitted": False,
                    "automatic_retry": False,
                },
            )
            _authority(operation_id, generation)
            row = _inspect(service, name)
            _accept_before(row, expected)

            _run(["docker", "kill", "--signal=SIGTERM", expected["container_id"]], timeout=20)

            deadline = time.monotonic() + 180
            while True:
                row = _inspect(service, name)
                if row["State"].get("Running") is False:
                    break
                if time.monotonic() >= deadline:
                    raise GracefulStopHalted(
                        "graceful stop deadline reached; no force or second signal permitted"
                    )
                time.sleep(0.5)
            if not _stopped_cleanly(row, expected):
                raise GracefulStopHalted("target did not exit cleanly")
            _write_new(
                root_fd,
                accepted_name,
                {
                    "operation_id": operation_id,
                    "generation": generation,
                    "service": service,
                    "container_id": expected["container_id"],
                    "image": expected["image"],
                    "restart_count": expected["restart_count"],
                    "signal": "SIGTERM",
                    "exit_code": 0,
                    "forced_kill": False,
                    "replayed_signal": False,
                    "reconciled_after_intent": False,
                },
            )

        final_authority = _authority(operation_id, generation)
        after_services = {}
        for service, name in TARGETS:
            row = _inspect(service, name)
            if not _stopped_cleanly(row, baseline[service]):
                raise GracefulStopHalted("final stopped target epoch differs")
            after_services[service] = _after(row)
        after = {"authority": final_authority, "services": after_services}
        result = asdict(accept(before=before, after=after))
        if _exists(root_fd, "graceful-stop-accepted.json"):
            if _read(root_fd, "graceful-stop-accepted.json") != result:
                raise GracefulStopHalted("final graceful-stop receipt differs")
        else:
            _write_new(root_fd, "graceful-stop-accepted.json", result)
        return result
    finally:
        os.close(root_fd)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--generation", required=True, type=int)
    parser.add_argument("--journal-root", required=True, type=Path)
    parser.add_argument("--prior-block", type=Path)
    args = parser.parse_args()
    try:
        result = execute(
            operation_id=args.operation_id,
            generation=args.generation,
            journal_root=args.journal_root,
            prior_block=args.prior_block,
        )
    except (GracefulStopHalted, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print(json.dumps({"status": "FR06_GRACEFUL_STOP_HALTED"}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
