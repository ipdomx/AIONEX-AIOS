#!/usr/bin/env python3
"""Validate the FR-06C2 PostgreSQL vault and restart overlays without mutation."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


class ContractError(RuntimeError):
    pass


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ContractError(f"{path.name} must contain an object")
    return value


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _render(dashboard: Path, env_file: Path, files: list[Path]) -> dict[str, Any]:
    cmd = ["docker", "compose", "--env-file", str(env_file), "--profile", "*"]
    for item in files:
        cmd += ["-f", str(item)]
    cmd += ["config", "--format", "json"]
    env = os.environ.copy()
    env["AIOS_ENV_FILE"] = str(env_file)
    out = subprocess.run(
        cmd,
        cwd=dashboard,
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    if out.returncode != 0:
        raise ContractError(
            f"docker compose config failed with exit code {out.returncode}; output withheld"
        )
    try:
        value = json.loads(out.stdout)
    except json.JSONDecodeError as exc:
        raise ContractError("compose config did not return JSON") from exc
    if not isinstance(value, dict):
        raise ContractError("compose config must be an object")
    return value


def _mounts(service: dict[str, Any]) -> list[dict[str, Any]]:
    return [x for x in (service.get("volumes") or []) if isinstance(x, dict)]


def _mount_for(service: dict[str, Any], target: str) -> dict[str, Any]:
    rows = [x for x in _mounts(service) if x.get("target") == target]
    if len(rows) != 1:
        raise ContractError(f"expected exactly one mount at {target}; found {len(rows)}")
    return rows[0]


def _db_clients(config: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for name, definition in config.get("services", {}).items():
        if not isinstance(definition, dict):
            continue
        environment = definition.get("environment") or {}
        if isinstance(environment, dict) and "DATABASE_URL" in environment:
            result.append(str(name))
    return sorted(result)


def _normalized_service(
    definition: dict[str, Any],
    *,
    allow_restart: bool,
    pgdata_target: str | None = None,
) -> dict[str, Any]:
    result = copy.deepcopy(definition)
    if allow_restart:
        result.pop("restart", None)
    if pgdata_target is not None:
        result["volumes"] = [
            item
            for item in (result.get("volumes") or [])
            if not (isinstance(item, dict) and item.get("target") == pgdata_target)
        ]
    return result


def validate(root: Path, env_file: Path) -> dict[str, Any]:
    root = root.resolve()
    dashboard = root / "web-dashboard"
    env_file = env_file.resolve()
    contract_path = root / "docs/project/receipts/FR-06C2-database-vault-contract.json"
    contract = _json(contract_path)
    names = contract["compose"]["accepted_files_before_c2"]
    accepted_files = [dashboard / name for name in names]
    db_overlay = dashboard / contract["compose"]["database_overlay"]
    admission_overlay = dashboard / contract["compose"]["database_admission_overlay"]
    for path in [env_file, contract_path, db_overlay, admission_overlay, *accepted_files]:
        if not path.is_file():
            raise ContractError(f"required source is missing: {path}")

    accepted = _render(dashboard, env_file, accepted_files)
    candidate = _render(
        dashboard, env_file, [*accepted_files, db_overlay, admission_overlay]
    )
    accepted_services = accepted.get("services") or {}
    candidate_services = candidate.get("services") or {}
    if set(accepted_services) != set(candidate_services):
        raise ContractError("database overlays changed the service set")

    database = contract["database"]
    target = database["container_target"]
    consumers = list(database["pgdata_consumers"])
    for service in consumers:
        before_mount = _mount_for(accepted_services[service], target)
        after_mount = _mount_for(candidate_services[service], target)
        if before_mount.get("type") != "volume" or before_mount.get("source") != database["legacy_compose_volume"]:
            raise ContractError(f"accepted PGDATA mount drifted for {service}")
        if after_mount.get("type") != "volume" or after_mount.get("source") != contract["candidate_vault"]["compose_volume"]:
            raise ContractError(f"candidate PGDATA does not use the database vault for {service}")
        if bool(after_mount.get("read_only", False)):
            raise ContractError(f"candidate PGDATA must remain writable for {service}")
        volume_options = after_mount.get("volume") or {}
        if volume_options.get("subpath") != contract["candidate_vault"]["target_subpath"]:
            raise ContractError(f"candidate PGDATA subpath drifted for {service}")
    postgres_before = accepted_services[database["service"]]
    postgres_after = candidate_services[database["service"]]

    legacy = database["legacy_compose_volume"]
    for service, definition in candidate_services.items():
        for mount in _mounts(definition):
            if mount.get("source") == legacy:
                raise ContractError(f"legacy PGDATA remains mounted by {service}")

    observed_clients = _db_clients(accepted)
    expected_clients = sorted(contract["database_clients"]["services"])
    if observed_clients != expected_clients:
        raise ContractError(
            f"database client matrix drifted; observed={observed_clients!r} expected={expected_clients!r}"
        )
    if len(expected_clients) != int(contract["database_clients"]["service_definition_count"]):
        raise ContractError("database client count does not match contract")
    for name in [*expected_clients, database["service"]]:
        if candidate_services[name].get("restart") != "no":
            raise ContractError(f"{name} is not guarded by restart:no")

    accepted_volumes = accepted.get("volumes") or {}
    candidate_volumes = candidate.get("volumes") or {}
    logical = contract["candidate_vault"]["compose_volume"]
    external_name = contract["candidate_vault"]["docker_volume"]
    definition = candidate_volumes.get(logical)
    if not isinstance(definition, dict) or definition.get("external") is not True or definition.get("name") != external_name:
        raise ContractError("candidate external database volume definition drifted")

    targeted_restart = set(expected_clients) | {database["service"]}
    for service in accepted_services:
        before = _normalized_service(
            accepted_services[service],
            allow_restart=service in targeted_restart,
            pgdata_target=target if service in consumers else None,
        )
        after = _normalized_service(
            candidate_services[service],
            allow_restart=service in targeted_restart,
            pgdata_target=target if service in consumers else None,
        )
        if before != after:
            raise ContractError(f"database overlays changed unrelated service configuration: {service}")

    before_top = copy.deepcopy(accepted)
    after_top = copy.deepcopy(candidate)
    before_top.pop("services", None)
    after_top.pop("services", None)
    before_vols = before_top.pop("volumes", {}) or {}
    after_vols = after_top.pop("volumes", {}) or {}
    if before_top != after_top:
        raise ContractError("database overlays changed unrelated top-level configuration")
    before_vols.pop(legacy, None)
    after_vols.pop(legacy, None)
    after_vols.pop(logical, None)
    if before_vols != after_vols:
        raise ContractError("database overlays changed unrelated volume definitions")

    socket_target = "/var/run/postgresql"
    if _mount_for(postgres_before, socket_target) != _mount_for(postgres_after, socket_target):
        raise ContractError("PostgreSQL socket mount drifted")
    workspace_target = "/workspace"
    if _mount_for(postgres_before, workspace_target) != _mount_for(postgres_after, workspace_target):
        raise ContractError("PostgreSQL workspace mount drifted")

    return {
        "schema_version": 1,
        "subpart": "FR-06C2A",
        "validation": "FR06C2_DATABASE_OVERLAY_PASS",
        "env_profile": env_file.name,
        "database_client_service_count": len(expected_clients),
        "postgres_restart_policy": "no",
        "database_clients_restart_policy": "no",
        "legacy_pgdata_mounts_after_merge": 0,
        "candidate_external_volume": external_name,
        "unrelated_service_or_top_level_drift": False,
        "production_changed": False,
        "contract_sha256": _sha(contract_path),
        "database_overlay_sha256": _sha(db_overlay),
        "database_admission_overlay_sha256": _sha(admission_overlay),
        "validator_sha256": _sha(Path(__file__).resolve()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--env-file", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    env_file = args.env_file or (root / "web-dashboard/.env.production.example")
    try:
        value = validate(root, env_file)
    except (ContractError, OSError, subprocess.SubprocessError) as exc:
        print(f"FR06C2_DATABASE_OVERLAY_FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(value, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
