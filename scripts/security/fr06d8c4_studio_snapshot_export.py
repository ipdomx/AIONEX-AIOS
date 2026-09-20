#!/usr/bin/env python3
"""Collect Studio drain snapshots through the one running backend container.

The backend module reads PostgreSQL only. This host wrapper identifies exactly
one production backend container, executes the exporter, validates its JSON
shape, and writes admission/studio/backup snapshots with mode 0600. It does not
change containers, admission, database state, or Studio files.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Any
from uuid import UUID

PROJECT = "web-dashboard"
SERVICE = "backend"
SCHEMA = "aionex.studio-drain-inputs.v1"


class SnapshotExportBlocked(RuntimeError):
    pass


def _run(args: list[str], timeout: int = 60) -> str:
    result = subprocess.run(args, check=False, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise SnapshotExportBlocked(f"command failed: {args[0]}")
    return result.stdout.strip()


def _uuid(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False


def _backend_container() -> str:
    rows = [
        value for value in _run([
            "docker", "ps", "--no-trunc",
            "--filter", f"label=com.docker.compose.project={PROJECT}",
            "--filter", f"label=com.docker.compose.service={SERVICE}",
            "--format", "{{.ID}}",
        ]).splitlines() if value
    ]
    if len(rows) != 1:
        raise SnapshotExportBlocked("expected exactly one running backend container")
    return rows[0]


def _validate(payload: Any, operation_id: str, generation: int) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != {"schema", "admission", "studio", "backup"}:
        raise SnapshotExportBlocked("snapshot bundle fields are not exact")
    if payload["schema"] != SCHEMA:
        raise SnapshotExportBlocked("snapshot bundle schema differs")
    admission = payload["admission"]
    backup = payload["backup"]
    studio = payload["studio"]
    if (
        not isinstance(admission, dict)
        or admission.get("status") != "closed"
        or admission.get("enabled") is not False
        or admission.get("operation_id") != operation_id
        or admission.get("generation") != generation
        or admission.get("full_host_closure") is not False
        or not isinstance(studio, dict)
        or studio.get("scope") != "studio_execution_threads"
        or studio.get("admission_closed") is not True
        or studio.get("coverage_unverified") is not True
        or studio.get("full_host_closure") is not False
        or not isinstance(backup, dict)
        or backup.get("scope") != "backup_cycles"
        or backup.get("operation_id") != operation_id
        or backup.get("generation") != generation
        or backup.get("coverage_unverified") is not True
        or backup.get("full_host_closure") is not False
    ):
        raise SnapshotExportBlocked("snapshot bundle authority or scope differs")
    return payload


def _write_private(path: Path, value: dict[str, Any]) -> None:
    if path.exists():
        raise SnapshotExportBlocked(f"snapshot already exists: {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        content = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()
        os.write(descriptor, content)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--generation", type=int, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        if not _uuid(args.operation_id) or args.generation < 7:
            raise SnapshotExportBlocked("invalid operation or generation")
        backend = _backend_container()
        raw = _run([
            "docker", "exec", backend,
            "python", "-m", "app.services.studio_drain_input_export",
            "--operation-id", args.operation_id,
            "--generation", str(args.generation),
        ], timeout=120)
        payload = _validate(json.loads(raw), args.operation_id, args.generation)
        _write_private(args.output_dir / "admission.json", payload["admission"])
        _write_private(args.output_dir / "studio.json", payload["studio"])
        _write_private(args.output_dir / "backup.json", payload["backup"])
    except (OSError, ValueError, json.JSONDecodeError, SnapshotExportBlocked):
        print("FR06D8C4_STUDIO_SNAPSHOT_EXPORT_BLOCKED")
        return 2
    print(json.dumps({
        "status": "studio_drain_snapshots_exported",
        "output_dir": str(args.output_dir),
        "files": ["admission.json", "studio.json", "backup.json"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
