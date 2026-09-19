#!/usr/bin/env python3
"""Prove the Studio application-writer epoch after maintenance closure.

This tool is observation-only. It never stops/restarts containers, mutates
admission, touches the Studio filesystem, changes database state, or authorizes
cleanup. It proves only that the currently running application writers were
created after a supplied closed-admission transition and that no unexpected
running compose container has a read-write Studio asset mount.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

SCHEMA = "aionex.studio-writer-epoch.v1"
PROJECT = "web-dashboard"
DESTINATION = "/var/lib/aionex/studio-assets"
WRITERS = frozenset({"backend", "studio-worker"})
READERS = frozenset({"backup-worker"})


class DrainBlocked(RuntimeError):
    pass


def _parse_time(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise DrainBlocked(f"{label} is missing")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise DrainBlocked(f"{label} is malformed") from exc
    if parsed.utcoffset() is None:
        raise DrainBlocked(f"{label} lacks timezone")
    return parsed.astimezone(UTC)


def _uuid(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False


def _sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _admission(value: Any) -> tuple[dict[str, Any], datetime]:
    if not isinstance(value, dict):
        raise DrainBlocked("admission snapshot is malformed")
    required = {
        "schema_version", "scope", "generation", "status", "enabled",
        "operation_id", "reason", "changed_at", "full_host_closure",
    }
    if set(value) != required:
        raise DrainBlocked("admission snapshot fields are not exact")
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"] < 7
        or type(value["generation"]) is not int
        or value["generation"] < value["schema_version"]
        or value["status"] != "closed"
        or value["enabled"] is not False
        or not _uuid(value["operation_id"])
        or not isinstance(value["reason"], str)
        or not value["reason"].strip()
        or value["full_host_closure"] is not False
        or not isinstance(value["scope"], str)
        or "studio_job_requests" not in value["scope"].split("+")
    ):
        raise DrainBlocked("admission snapshot is not a closed Studio authority")
    return value, _parse_time(value["changed_at"], "admission changed_at")


def _studio_snapshot(value: Any) -> tuple[dict[str, Any], datetime]:
    if not isinstance(value, dict):
        raise DrainBlocked("Studio snapshot is malformed")
    if (
        value.get("scope") != "studio_execution_threads"
        or value.get("admission_closed") is not True
        or value.get("full_host_closure") is not False
        or value.get("coverage_unverified") is not True
        or not isinstance(value.get("executions"), list)
        or not isinstance(value.get("postcrash_observations"), list)
    ):
        raise DrainBlocked("Studio snapshot does not preserve the source-only boundary")
    for item in value["postcrash_observations"]:
        if (
            not isinstance(item, dict)
            or item.get("requires_reconciliation") is not True
            or item.get("process_drain_verified") is not False
            or item.get("cleanup_authorized") is not False
        ):
            raise DrainBlocked("Studio crash observation was prematurely cleared")
    return value, _parse_time(value.get("observed_at"), "Studio observed_at")


def _mount(container: dict[str, Any]) -> dict[str, Any] | None:
    mounts = container.get("Mounts")
    if not isinstance(mounts, list):
        raise DrainBlocked("container mount inventory is missing")
    matches = [m for m in mounts if isinstance(m, dict) and m.get("Destination") == DESTINATION]
    if len(matches) > 1:
        raise DrainBlocked("container has ambiguous Studio mounts")
    return matches[0] if matches else None


def evaluate(
    *,
    admission: dict[str, Any],
    studio_snapshot: dict[str, Any],
    containers: list[dict[str, Any]],
    merge_sha: str,
) -> dict[str, Any]:
    """Validate a point-in-time application-writer epoch without side effects."""
    if (
        not isinstance(merge_sha, str)
        or len(merge_sha) != 40
        or any(ch not in "0123456789abcdef" for ch in merge_sha)
    ):
        raise DrainBlocked("merge SHA is invalid")
    authority, closed_at = _admission(admission)
    studio, observed_at = _studio_snapshot(studio_snapshot)

    running: list[dict[str, Any]] = []
    for item in containers:
        if not isinstance(item, dict):
            raise DrainBlocked("container inspection is malformed")
        config = item.get("Config") or {}
        state = item.get("State") or {}
        labels = config.get("Labels") or {}
        if labels.get("com.docker.compose.project") != PROJECT:
            continue
        if state.get("Running") is not True or state.get("Status") != "running":
            continue
        service = labels.get("com.docker.compose.service")
        identifier = item.get("Id")
        if not isinstance(service, str) or not service or not isinstance(identifier, str):
            raise DrainBlocked("running compose container identity is incomplete")
        running.append(item)

    by_service: dict[str, list[dict[str, Any]]] = {}
    volume_sources: set[str] = set()
    mount_rows: list[dict[str, Any]] = []
    for item in running:
        labels = (item.get("Config") or {}).get("Labels") or {}
        service = labels["com.docker.compose.service"]
        by_service.setdefault(service, []).append(item)
        mount = _mount(item)
        if mount is None:
            continue
        rw = mount.get("RW")
        if type(rw) is not bool:
            raise DrainBlocked("Studio mount mode is unavailable")
        source = mount.get("Source")
        if not isinstance(source, str) or not source:
            raise DrainBlocked("Studio mount source is unavailable")
        volume_sources.add(source)
        mount_rows.append({
            "service": service,
            "container_id": item["Id"],
            "rw": rw,
            "source": source,
            "type": mount.get("Type"),
            "name": mount.get("Name"),
        })
        if rw and service not in WRITERS:
            raise DrainBlocked(f"unexpected Studio writer: {service}")
        if not rw and service not in WRITERS | READERS:
            # Unknown readers are not writers, but scope must be explicit before cleanup.
            raise DrainBlocked(f"unexpected Studio reader: {service}")

    if len(volume_sources) != 1:
        raise DrainBlocked("Studio volume identity is ambiguous")

    writers: list[dict[str, Any]] = []
    for service in sorted(WRITERS):
        rows = by_service.get(service, [])
        if len(rows) != 1:
            raise DrainBlocked(f"expected exactly one running {service} container")
        item = rows[0]
        mount = _mount(item)
        if mount is None or mount.get("RW") is not True:
            raise DrainBlocked(f"{service} lacks the required read-write Studio mount")
        started = _parse_time((item.get("State") or {}).get("StartedAt"), f"{service} StartedAt")
        if started <= closed_at:
            raise DrainBlocked(f"{service} was not restarted after admission closure")
        writers.append({
            "service": service,
            "container_id": item["Id"],
            "started_at": started.isoformat(),
            "restart_count": item.get("RestartCount"),
        })

    if observed_at <= max(_parse_time(row["started_at"], row["service"]) for row in writers):
        raise DrainBlocked("Studio snapshot predates the restarted writer epoch")

    reader_rows = [row for row in mount_rows if not row["rw"]]
    receipt = {
        "schema": SCHEMA,
        "observed_at": datetime.now(UTC).isoformat(),
        "merge_sha": merge_sha,
        "admission": {
            "operation_id": authority["operation_id"],
            "generation": authority["generation"],
            "changed_at": closed_at.isoformat(),
            "snapshot_sha256": _sha(authority),
        },
        "studio_snapshot": {
            "observed_at": observed_at.isoformat(),
            "snapshot_sha256": _sha(studio),
            "postcrash_observation_count": len(studio["postcrash_observations"]),
        },
        "writers": writers,
        "readers": sorted(reader_rows, key=lambda row: (row["service"], row["container_id"])),
        "studio_volume_source": next(iter(volume_sources)),
        "application_writer_epoch_verified": True,
        "process_drain_verified": False,
        "host_process_scan_verified": False,
        "backup_cycle_drain_verified": False,
        "cleanup_authorized": False,
        "filesystem_mutation_performed": False,
        "full_host_closure": False,
    }
    receipt["receipt_sha256"] = _sha(receipt)
    return receipt


def _run(args: list[str], timeout: int = 30) -> str:
    result = subprocess.run(args, check=False, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise DrainBlocked(f"command failed: {args[0]}")
    return result.stdout.strip()


def _git_gate(root: Path, merge_sha: str) -> None:
    heads = _run(["git", "-C", str(root), "rev-parse", "HEAD", "origin/main"]).splitlines()
    if heads != [merge_sha, merge_sha]:
        raise DrainBlocked("source is not exact accepted main")
    if _run(["git", "-C", str(root), "status", "--porcelain=v1"]):
        raise DrainBlocked("source tree is dirty")


def _containers() -> list[dict[str, Any]]:
    ids = [
        line for line in _run([
            "docker", "ps", "--no-trunc",
            "--filter", f"label=com.docker.compose.project={PROJECT}",
            "--format", "{{.ID}}",
        ]).splitlines() if line
    ]
    if not ids:
        raise DrainBlocked("running compose container inventory is empty")
    value = json.loads(_run(["docker", "inspect", *ids], timeout=60))
    if not isinstance(value, list) or len(value) != len(ids):
        raise DrainBlocked("container inspection set is incomplete")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--admission-snapshot", type=Path, required=True)
    parser.add_argument("--studio-snapshot", type=Path, required=True)
    parser.add_argument("--merge-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        _git_gate(args.root, args.merge_sha)
        admission = json.loads(args.admission_snapshot.read_text(encoding="utf-8"))
        studio = json.loads(args.studio_snapshot.read_text(encoding="utf-8"))
        receipt = evaluate(
            admission=admission,
            studio_snapshot=studio,
            containers=_containers(),
            merge_sha=args.merge_sha,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        if args.output.exists():
            raise DrainBlocked("writer epoch receipt already exists")
        args.output.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        args.output.chmod(0o600)
    except (OSError, ValueError, json.JSONDecodeError, DrainBlocked) as exc:
        print(f"FR06D8C4B_STUDIO_WRITER_EPOCH_BLOCKED: {type(exc).__name__}", flush=True)
        return 2
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
