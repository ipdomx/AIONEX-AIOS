#!/usr/bin/env python3
"""Read-only, fail-closed NEW-host FR-09 encrypted-runtime space preflight.

This tool observes the actual host filesystems. It NEVER starts a load test,
validates FR-08 acceptance, authorizes spending, or verifies lab isolation.
Avoid passing the 3-TB root filesystem as if it were the Docker runtime vault.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import socket
from typing import Any

GIB = 1024 ** 3
EXPECTED_HOST = "nc-ph-4354"
FILESYSTEMS = {
    "root": "/",
    "docker": "/var/lib/docker",
    "containerd": "/var/lib/containerd",
}


def observe_storage() -> dict[str, Any]:
    """Kernel/filesystem reads only; no Docker socket, secrets, or writes."""
    rows: dict[str, dict[str, int | bool]] = {}
    for name, path in FILESYSTEMS.items():
        candidate = Path(path)
        if not candidate.is_dir() or candidate.is_symlink():
            raise OSError(f"{name} filesystem directory missing or symlinked")
        usage = shutil.disk_usage(path)
        rows[name] = {
            "total_bytes": int(usage.total),
            "free_bytes": int(usage.free),
            "device_id": int(os.stat(path).st_dev),
            "mountpoint": bool(os.path.ismount(path)),
        }
    return {"hostname": socket.gethostname(), "filesystems": rows}


def evaluate_storage(
    observation: dict[str, Any],
    *,
    expected_hostname: str = EXPECTED_HOST,
    minimum_free_bytes: int = 40 * GIB,
) -> dict[str, Any]:
    """Evaluate a recorded observation without performing any I/O."""
    blockers: list[str] = []
    hostname = observation.get("hostname")
    rows = observation.get("filesystems")
    rows = rows if isinstance(rows, dict) else {}
    root, docker, containerd = (rows.get(key) for key in FILESYSTEMS)
    if hostname != expected_hostname:
        blockers.append("not the authorized NEW production host")
    if any(not isinstance(row, dict) for row in (root, docker, containerd)):
        blockers.append("missing required filesystem observation")
    else:
        for name, row in (("root", root), ("docker", docker), ("containerd", containerd)):
            if (
                type(row.get("total_bytes")) is not int
                or row["total_bytes"] <= 0
                or type(row.get("free_bytes")) is not int
                or row["free_bytes"] < 0
                or row["free_bytes"] > row["total_bytes"]
                or type(row.get("device_id")) is not int
            ):
                blockers.append(f"invalid {name} filesystem observation")
        if not any(item.startswith("invalid ") for item in blockers):
            if not docker.get("mountpoint") or not containerd.get("mountpoint"):
                blockers.append("encrypted runtime mountpoint is not mounted")
            if root["device_id"] == docker["device_id"]:
                blockers.append("Docker runtime appears on root filesystem, not separately verified vault")
            if docker["device_id"] != containerd["device_id"]:
                blockers.append("Docker/containerd runtime volumes are not the same reviewed vault")
            if root["free_bytes"] < minimum_free_bytes:
                blockers.append("root filesystem free space is below the capacity gate")
            if min(docker["free_bytes"], containerd["free_bytes"]) < minimum_free_bytes:
                blockers.append("encrypted Docker/containerd vault free space is below the capacity gate")

    return {
        "schema": "aionex.fr09.observed-storage-preflight.v1",
        "status": "STORAGE_PRECHECK_PASS" if not blockers else "HOLD_STORAGE",
        "expected_host": expected_hostname,
        "observed_host": hostname if isinstance(hostname, str) else None,
        "minimum_free_bytes": minimum_free_bytes,
        "observed": rows,
        "blockers": blockers,
        "fr08_runtime_accepted": False,
        "isolated_lab_verified": False,
        "load_test_authorized": False,
        "load_test_started": False,
        "customer_data_accessed": False,
        "external_provider_calls": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minimum-free-gib", type=int, default=40)
    args = parser.parse_args()
    if not 40 <= args.minimum_free_gib <= 1024:
        parser.error("minimum-free-gib must be between 40 and 1024")
    try:
        result = evaluate_storage(
            observe_storage(), minimum_free_bytes=args.minimum_free_gib * GIB
        )
    except (OSError, ValueError) as exc:
        print(json.dumps({
            "schema": "aionex.fr09.observed-storage-preflight.v1",
            "status": "HOLD_STORAGE",
            "error_type": type(exc).__name__,
            "load_test_authorized": False,
            "load_test_started": False,
        }, sort_keys=True))
        return 3
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "STORAGE_PRECHECK_PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
