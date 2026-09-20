#!/usr/bin/env python3
"""Prove Studio application/backup runtime drain without authorizing cleanup.

Consumes an immutable C4B1 writer-epoch receipt plus a backup-cycle snapshot for
the same maintenance operation/generation. It rechecks the current running
Compose containers and produces another point-in-time receipt. It never stops or
restarts containers, changes admission/database state, scans host process file
references, or mutates the Studio filesystem.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

WRITER_SCHEMA = "aionex.studio-writer-epoch.v1"
SCHEMA = "aionex.studio-runtime-drain.v1"
PROJECT = "web-dashboard"
DESTINATION = "/var/lib/aionex/studio-assets"
WRITERS = frozenset({"backend", "studio-worker"})
READERS = frozenset({"backup-worker"})
ONE_SHOT = "backup-asset-root-init"


class RuntimeDrainBlocked(RuntimeError):
    pass


def _sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _time(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise RuntimeDrainBlocked(f"{label} is missing")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise RuntimeDrainBlocked(f"{label} is malformed") from exc
    if parsed.utcoffset() is None:
        raise RuntimeDrainBlocked(f"{label} lacks timezone")
    return parsed.astimezone(UTC)


def _writer_receipt(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeDrainBlocked("writer receipt is malformed")
    required = {
        "schema",
        "observed_at",
        "merge_sha",
        "admission",
        "studio_snapshot",
        "writers",
        "readers",
        "studio_volume_source",
        "application_writer_epoch_verified",
        "process_drain_verified",
        "host_process_scan_verified",
        "backup_cycle_drain_verified",
        "cleanup_authorized",
        "filesystem_mutation_performed",
        "full_host_closure",
        "receipt_sha256",
    }
    if set(value) != required:
        raise RuntimeDrainBlocked("writer receipt fields are not exact")
    digest = value["receipt_sha256"]
    body = {key: item for key, item in value.items() if key != "receipt_sha256"}
    if (
        value["schema"] != WRITER_SCHEMA
        or not isinstance(digest, str)
        or digest != _sha(body)
        or value["application_writer_epoch_verified"] is not True
        or value["process_drain_verified"] is not False
        or value["host_process_scan_verified"] is not False
        or value["backup_cycle_drain_verified"] is not False
        or value["cleanup_authorized"] is not False
        or value["filesystem_mutation_performed"] is not False
        or value["full_host_closure"] is not False
        or not isinstance(value["studio_volume_source"], str)
        or not value["studio_volume_source"]
    ):
        raise RuntimeDrainBlocked("writer receipt is not an accepted C4B1 receipt")
    _time(value["observed_at"], "writer observed_at")
    return value


def _backup_snapshot(value: Any, writer: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeDrainBlocked("backup snapshot is malformed")
    required = {
        "scope",
        "observed_at",
        "operation_id",
        "generation",
        "active_count",
        "unresolved_count",
        "expired_count",
        "unfinished_count",
        "coverage_unverified",
        "full_host_closure",
    }
    if set(value) != required:
        raise RuntimeDrainBlocked("backup snapshot fields are not exact")
    admission = writer["admission"]
    if (
        value["scope"] != "backup_cycles"
        or value["operation_id"] != admission.get("operation_id")
        or value["generation"] != admission.get("generation")
        or value["coverage_unverified"] is not True
        or value["full_host_closure"] is not False
    ):
        raise RuntimeDrainBlocked("backup snapshot authority differs")
    for key in ("active_count", "unresolved_count", "expired_count", "unfinished_count"):
        if type(value[key]) is not int or value[key] != 0:
            raise RuntimeDrainBlocked(f"backup snapshot is not drained: {key}")
    if _time(value["observed_at"], "backup observed_at") <= _time(
        writer["observed_at"], "writer observed_at"
    ):
        raise RuntimeDrainBlocked("backup snapshot predates writer-epoch receipt")
    return value


def _mount(item: dict[str, Any]) -> dict[str, Any] | None:
    mounts = item.get("Mounts")
    if not isinstance(mounts, list):
        raise RuntimeDrainBlocked("container mount inventory is missing")
    matches = [
        mount
        for mount in mounts
        if isinstance(mount, dict) and mount.get("Destination") == DESTINATION
    ]
    if len(matches) > 1:
        raise RuntimeDrainBlocked("container has ambiguous Studio mounts")
    return matches[0] if matches else None


def _service(item: dict[str, Any]) -> str:
    labels = (item.get("Config") or {}).get("Labels") or {}
    service = labels.get("com.docker.compose.service")
    if not isinstance(service, str) or not service:
        raise RuntimeDrainBlocked("compose service identity is missing")
    return service


def _running_project(containers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for item in containers:
        if not isinstance(item, dict):
            raise RuntimeDrainBlocked("container inspection is malformed")
        config = item.get("Config") or {}
        labels = config.get("Labels") or {}
        state = item.get("State") or {}
        if labels.get("com.docker.compose.project") != PROJECT:
            continue
        if state.get("Running") is not True or state.get("Status") != "running":
            continue
        if not isinstance(item.get("Id"), str) or not item["Id"]:
            raise RuntimeDrainBlocked("running container id is missing")
        _service(item)
        rows.append(item)
    return rows


def evaluate(
    *,
    writer_receipt: dict[str, Any],
    backup_snapshot: dict[str, Any],
    containers: list[dict[str, Any]],
) -> dict[str, Any]:
    """Prove the writer epoch stayed stable and backup-cycle registry is empty."""
    writer = _writer_receipt(writer_receipt)
    backup = _backup_snapshot(backup_snapshot, writer)
    running = _running_project(containers)

    by_service: dict[str, list[dict[str, Any]]] = {}
    mounted = []
    for item in running:
        service = _service(item)
        by_service.setdefault(service, []).append(item)
        mount = _mount(item)
        if mount is not None:
            mounted.append((service, item, mount))

    if by_service.get(ONE_SHOT):
        raise RuntimeDrainBlocked("one-shot Studio root initializer is running")

    expected_writers = {
        row["service"]: row
        for row in writer["writers"]
        if isinstance(row, dict) and isinstance(row.get("service"), str)
    }
    if set(expected_writers) != WRITERS or len(writer["writers"]) != len(WRITERS):
        raise RuntimeDrainBlocked("writer receipt writer set differs")

    for service in sorted(WRITERS):
        rows = by_service.get(service, [])
        if len(rows) != 1:
            raise RuntimeDrainBlocked(f"runtime writer count differs: {service}")
        item = rows[0]
        expected = expected_writers[service]
        if item["Id"] != expected.get("container_id"):
            raise RuntimeDrainBlocked(f"runtime writer container changed: {service}")
        if (item.get("RestartCount")) != expected.get("restart_count"):
            raise RuntimeDrainBlocked(f"runtime writer restart count changed: {service}")
        if _time((item.get("State") or {}).get("StartedAt"), service) != _time(
            expected.get("started_at"), service
        ):
            raise RuntimeDrainBlocked(f"runtime writer start time changed: {service}")

    expected_readers = {
        row["service"]: row
        for row in writer["readers"]
        if isinstance(row, dict) and isinstance(row.get("service"), str)
    }
    if set(expected_readers) != READERS or len(writer["readers"]) != len(READERS):
        raise RuntimeDrainBlocked("writer receipt reader set differs")
    for service in sorted(READERS):
        rows = by_service.get(service, [])
        if len(rows) != 1 or rows[0]["Id"] != expected_readers[service].get("container_id"):
            raise RuntimeDrainBlocked(f"runtime reader container changed: {service}")

    source = writer["studio_volume_source"]
    for service, item, mount in mounted:
        if mount.get("Source") != source or type(mount.get("RW")) is not bool:
            raise RuntimeDrainBlocked("runtime Studio volume identity changed")
        if mount["RW"] and service not in WRITERS:
            raise RuntimeDrainBlocked(f"unexpected runtime Studio writer: {service}")
        if not mount["RW"] and service not in READERS:
            raise RuntimeDrainBlocked(f"unexpected runtime Studio reader: {service}")

    receipt = {
        "schema": SCHEMA,
        "observed_at": datetime.now(UTC).isoformat(),
        "writer_receipt_sha256": writer["receipt_sha256"],
        "merge_sha": writer["merge_sha"],
        "operation_id": writer["admission"]["operation_id"],
        "generation": writer["admission"]["generation"],
        "studio_volume_source": source,
        "writer_container_ids": sorted(
            row["container_id"] for row in writer["writers"]
        ),
        "backup_snapshot_sha256": _sha(backup),
        "application_writer_epoch_verified": True,
        "runtime_container_epoch_stable": True,
        "backup_cycle_drain_verified": True,
        "process_drain_verified": False,
        "host_process_scan_verified": False,
        "cleanup_authorized": False,
        "filesystem_mutation_performed": False,
        "full_host_closure": False,
    }
    receipt["receipt_sha256"] = _sha(receipt)
    return receipt


def _run(args: list[str], timeout: int = 30) -> str:
    result = subprocess.run(args, check=False, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeDrainBlocked(f"command failed: {args[0]}")
    return result.stdout.strip()


def _containers() -> list[dict[str, Any]]:
    ids = [
        value
        for value in _run([
            "docker",
            "ps",
            "--no-trunc",
            "--filter",
            f"label=com.docker.compose.project={PROJECT}",
            "--format",
            "{{.ID}}",
        ]).splitlines()
        if value
    ]
    if not ids:
        raise RuntimeDrainBlocked("running compose inventory is empty")
    value = json.loads(_run(["docker", "inspect", *ids], timeout=60))
    if not isinstance(value, list) or len(value) != len(ids):
        raise RuntimeDrainBlocked("container inspection set is incomplete")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--writer-receipt", type=Path, required=True)
    parser.add_argument("--backup-snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        writer = json.loads(args.writer_receipt.read_text(encoding="utf-8"))
        backup = json.loads(args.backup_snapshot.read_text(encoding="utf-8"))
        receipt = evaluate(
            writer_receipt=writer,
            backup_snapshot=backup,
            containers=_containers(),
        )
        if args.output.exists():
            raise RuntimeDrainBlocked("runtime drain receipt already exists")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(receipt, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        args.output.chmod(0o600)
    except (OSError, ValueError, json.JSONDecodeError, RuntimeDrainBlocked) as exc:
        print(f"FR06D8C4B2_STUDIO_RUNTIME_DRAIN_BLOCKED: {type(exc).__name__}")
        return 2
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
