#!/usr/bin/env python3
"""Journaled one-time resume of the three FR-06 final-drain services.

This operator exists only to restore the exact pre-C5D 36-container topology
after an accepted final graceful stop. It starts the same stopped container
epochs under the same closed maintenance authority. It never recreates,
restarts, stops, kills, updates, or enables automatic restart for a container.

Every docker start has a durable create-only intent. If an intent exists, a
later invocation may only reconcile an already-running exact healthy epoch; it
never repeats docker start for a stopped or ambiguous target.
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

ROOT = Path("/opt/AIOS")
JOURNAL_BASE = Path("/var/lib/aionex/fr06-final-maintenance")
TARGETS = (
    ("telegram-worker", "web-dashboard-telegram-worker-1"),
    ("user-telegram-worker", "web-dashboard-user-telegram-worker-1"),
    ("operations-observer", "web-dashboard-operations-observer-1"),
)
SCHEMA = "aionex.fr06c5d12-maintenance-resume.v1"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.security.fr06c5d11_graceful_stop_acceptance import accept as accept_stop
from scripts.security.fr06c5d11_graceful_stop_operator import (
    GracefulStopHalted,
    _authority,
    _canon,
    _run,
    _safe_root,
    _write_new,
)

class MaintenanceResumeHalted(RuntimeError):
    """Resume cannot continue without risking replay or epoch drift."""


def _read_private(path: Path) -> Any:
    resolved = path.resolve(strict=True)
    base = JOURNAL_BASE.resolve()
    if base not in resolved.parents:
        raise MaintenanceResumeHalted("evidence must be below the private FR-06 journal root")
    fd = os.open(resolved, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        st = os.fstat(fd)
        if (
            not stat.S_ISREG(st.st_mode)
            or st.st_uid != os.geteuid()
            or st.st_nlink != 1
            or stat.S_IMODE(st.st_mode) != 0o600
            or st.st_size > 1024 * 1024
        ):
            raise MaintenanceResumeHalted("unsafe prior evidence file")
        raw = os.read(fd, st.st_size + 1)
        if len(raw) != st.st_size or not raw.endswith(b"\n"):
            raise MaintenanceResumeHalted("incomplete prior evidence file")
        return json.loads(raw)
    finally:
        os.close(fd)


def _read_journal(root_fd: int, name: str) -> Any:
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=root_fd)
    try:
        st = os.fstat(fd)
        if (
            not stat.S_ISREG(st.st_mode)
            or st.st_uid != os.geteuid()
            or st.st_nlink != 1
            or stat.S_IMODE(st.st_mode) != 0o600
            or st.st_size > 1024 * 1024
        ):
            raise MaintenanceResumeHalted("unsafe resume journal")
        raw = os.read(fd, st.st_size + 1)
        if len(raw) != st.st_size or not raw.endswith(b"\n"):
            raise MaintenanceResumeHalted("incomplete resume journal")
        return json.loads(raw)
    finally:
        os.close(fd)


def _exists(root_fd: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=root_fd, follow_symlinks=False)
        return True
    except FileNotFoundError:
        return False


def _source_identity() -> dict[str, str]:
    head = _run(["git", "-C", str(ROOT), "rev-parse", "HEAD"])
    origin = _run(["git", "-C", str(ROOT), "rev-parse", "origin/main"])
    if head != origin or _run(["git", "-C", str(ROOT), "status", "--porcelain"]):
        raise MaintenanceResumeHalted("production source is not clean exact origin/main")
    script = Path(__file__).resolve()
    return {"source_commit": head, "operator_sha256": hashlib.sha256(script.read_bytes()).hexdigest()}


def _inspect(service: str, name: str) -> dict[str, Any]:
    rows = json.loads(_run(["docker", "inspect", name]))
    if not isinstance(rows, list) or len(rows) != 1:
        raise MaintenanceResumeHalted("target identity unavailable")
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
        or re.fullmatch(r"[0-9a-f]{64}", row["Id"]) is None
        or not isinstance(row.get("Image"), str)
    ):
        raise MaintenanceResumeHalted("target identity/restart contract differs")
    health = state.get("Health", {}).get("Status")
    if state.get("Running") is True and health not in (None, "starting", "healthy"):
        raise MaintenanceResumeHalted("running target entered unacceptable health")
    return row


def _stopped(row: dict[str, Any], prior: dict[str, Any]) -> bool:
    return (
        row["Id"] == prior["container_id"]
        and row["RestartCount"] == prior["restart_count"]
        and row["State"].get("Running") is False
        and row["State"].get("ExitCode") == 0
        and row["State"].get("OOMKilled") is False
        and row.get("HostConfig", {}).get("RestartPolicy", {}).get("Name") == "no"
    )


def _running(row: dict[str, Any], baseline: dict[str, Any]) -> bool:
    health = row.get("State", {}).get("Health", {}).get("Status")
    return (
        row["Id"] == baseline["container_id"]
        and row["Image"] == baseline["image"]
        and row["RestartCount"] == baseline["restart_count"]
        and row["State"].get("Running") is True
        and row["State"].get("Status") == "running"
        and row["State"].get("OOMKilled") is False
        and health in (None, "healthy")
        and row.get("HostConfig", {}).get("RestartPolicy", {}).get("Name") == "no"
    )


def _prior(prior_root: Path, operation_id: str, generation: int) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    before = _read_private(prior_root / "graceful-before.json")
    after = _read_private(prior_root / "graceful-after.json")
    accepted = _read_private(prior_root / "graceful-accepted.json")
    expected = asdict(accept_stop(before=before, after=after))
    if accepted != expected:
        raise MaintenanceResumeHalted("prior graceful-stop acceptance differs")
    if (
        accepted.get("operation_id") != operation_id
        or accepted.get("generation") != generation
        or accepted.get("graceful_stop_verified") is not True
        or accepted.get("full_host_closure") is not False
    ):
        raise MaintenanceResumeHalted("prior graceful-stop authority differs")
    return before, after, accepted


def execute(
    *,
    operation_id: str,
    generation: int,
    prior_root: Path,
    journal_root: Path,
) -> dict[str, Any]:
    authority = _authority(operation_id, generation)
    before, after, prior_acceptance = _prior(prior_root, operation_id, generation)
    source = _source_identity()
    root_fd = _safe_root(journal_root)
    try:
        session_name = "resume-session-intent.json"
        if not _exists(root_fd, session_name):
            baseline: dict[str, Any] = {}
            for service, name in TARGETS:
                prior = after["services"][service]
                row = _inspect(service, name)
                if not _stopped(row, prior):
                    raise MaintenanceResumeHalted("exact clean stopped target required before resume")
                baseline[service] = {
                    "container_id": row["Id"],
                    "image": row["Image"],
                    "restart_count": row["RestartCount"],
                    "finished_at": row["State"].get("FinishedAt"),
                }
            _write_new(
                root_fd,
                session_name,
                {
                    "schema": SCHEMA,
                    "operation_id": operation_id,
                    "generation": generation,
                    "authority": authority,
                    "source": source,
                    "services": [service for service, _ in TARGETS],
                    "prior_graceful_sha256": hashlib.sha256(
                        _canon(prior_acceptance)
                    ).hexdigest(),
                    "baseline": baseline,
                    "effect": "docker-start-exact-existing-container",
                    "automatic_retry": False,
                    "prior_full_host_closure_invalidated": True,
                },
            )
        session = _read_journal(root_fd, session_name)
        if (
            session.get("schema") != SCHEMA
            or session.get("operation_id") != operation_id
            or session.get("generation") != generation
            or session.get("authority") != authority
            or session.get("source") != source
            or session.get("services") != [service for service, _ in TARGETS]
            or session.get("automatic_retry") is not False
            or session.get("prior_full_host_closure_invalidated") is not True
        ):
            raise MaintenanceResumeHalted("existing resume session differs")

        baseline = session["baseline"]
        for service, name in TARGETS:
            intent_name = f"{service}-start-intent.json"
            accepted_name = f"{service}-start-accepted.json"
            expected = baseline[service]
            row = _inspect(service, name)

            if _exists(root_fd, accepted_name):
                if not _running(row, expected):
                    raise MaintenanceResumeHalted("accepted resumed target epoch differs")
                continue

            if _exists(root_fd, intent_name):
                deadline = time.monotonic() + 180
                while True:
                    row = _inspect(service, name)
                    if _running(row, expected):
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
                                "reconciled_after_intent": True,
                                "replayed_start": False,
                            },
                        )
                        break
                    if row["State"].get("Running") is False:
                        raise MaintenanceResumeHalted(
                            "unresolved prior start intent while target is stopped; refusing replay"
                        )
                    if time.monotonic() >= deadline:
                        raise MaintenanceResumeHalted(
                            "started target did not become healthy; no restart/replay permitted"
                        )
                    time.sleep(1)
                continue

            prior = after["services"][service]
            if not _stopped(row, prior) or row["Image"] != expected["image"]:
                raise MaintenanceResumeHalted("stopped target drifted before start intent")
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
                    "effect": "docker-start",
                    "automatic_retry": False,
                },
            )
            _authority(operation_id, generation)
            row = _inspect(service, name)
            if not _stopped(row, prior) or row["Image"] != expected["image"]:
                raise MaintenanceResumeHalted("target changed after durable start intent")

            _run(["docker", "start", expected["container_id"]], timeout=30)
            deadline = time.monotonic() + 180
            while True:
                row = _inspect(service, name)
                if _running(row, expected):
                    break
                if row["Id"] != expected["container_id"] or row["Image"] != expected["image"] or row["RestartCount"] != expected["restart_count"]:
                    raise MaintenanceResumeHalted("target epoch changed after start")
                if row["State"].get("Running") is False:
                    raise MaintenanceResumeHalted("target exited after start; no retry permitted")
                if time.monotonic() >= deadline:
                    raise MaintenanceResumeHalted("target health deadline reached; no restart permitted")
                time.sleep(1)
            _authority(operation_id, generation)
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
                    "reconciled_after_intent": False,
                    "replayed_start": False,
                },
            )

        final_authority = _authority(operation_id, generation)
        final = {}
        for service, name in TARGETS:
            row = _inspect(service, name)
            if not _running(row, baseline[service]):
                raise MaintenanceResumeHalted("final resumed target epoch differs")
            final[service] = {
                "container_id": row["Id"],
                "image": row["Image"],
                "restart_count": row["RestartCount"],
                "running": True,
                "healthy": row.get("State", {}).get("Health", {}).get("Status") in (None, "healthy"),
                "restart_policy": "no",
            }
        result = {
            "schema": SCHEMA,
            "operation_id": operation_id,
            "generation": generation,
            "authority": final_authority,
            "services": final,
            "resume_verified": True,
            "prior_full_host_closure_invalidated": True,
            "full_host_closure": False,
            "production_activation_authorized": False,
        }
        if _exists(root_fd, "maintenance-resume-accepted.json"):
            if _read_journal(root_fd, "maintenance-resume-accepted.json") != result:
                raise MaintenanceResumeHalted("resume acceptance receipt differs")
        else:
            _write_new(root_fd, "maintenance-resume-accepted.json", result)
        return result
    finally:
        os.close(root_fd)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--generation", required=True, type=int)
    parser.add_argument("--prior-root", required=True, type=Path)
    parser.add_argument("--journal-root", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = execute(
            operation_id=args.operation_id,
            generation=args.generation,
            prior_root=args.prior_root,
            journal_root=args.journal_root,
        )
    except (
        MaintenanceResumeHalted,
        GracefulStopHalted,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
    ):
        print(json.dumps({"status": "FR06_MAINTENANCE_RESUME_HALTED"}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
