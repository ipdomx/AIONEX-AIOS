#!/usr/bin/env python3
"""Render-only validator for FR-06C3C1 backup/operations Compose overlays."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
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
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _render(dashboard: Path, env_file: Path, files: list[Path]) -> dict[str, Any]:
    command = ["docker", "compose", "--env-file", str(env_file), "--profile", "*"]
    for path in files:
        command += ["-f", str(path)]
    command += ["config", "--format", "json"]
    env = os.environ.copy()
    env["AIOS_ENV_FILE"] = str(env_file)
    result = subprocess.run(command, cwd=dashboard, env=env, capture_output=True, text=True, timeout=90, check=False)
    if result.returncode != 0:
        raise ContractError(f"docker compose config failed with exit code {result.returncode}; output withheld")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ContractError("compose config did not return JSON") from exc
    if not isinstance(value, dict):
        raise ContractError("compose config must be an object")
    return value


def _mounts(service: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in (service.get("volumes") or []) if isinstance(item, dict)]


def _mount(service: dict[str, Any], target: str) -> dict[str, Any]:
    found = [item for item in _mounts(service) if item.get("target") == target]
    if len(found) != 1:
        raise ContractError(f"expected one mount at {target}; found {len(found)}")
    return found[0]


def _strip_target(definition: dict[str, Any], target: str | None, *, ignore_restart: bool = False) -> dict[str, Any]:
    value = copy.deepcopy(definition)
    if ignore_restart:
        value.pop("restart", None)
    if target:
        value["volumes"] = [item for item in (value.get("volumes") or []) if not (isinstance(item, dict) and item.get("target") == target)]
    return value


def _assert_candidate_mount(service: dict[str, Any], target: str, source: str, subpath: str, read_only: bool) -> None:
    item = _mount(service, target)
    if item.get("type") != "volume" or item.get("source") != source:
        raise ContractError(f"candidate mount at {target} does not use {source}")
    if bool(item.get("read_only", False)) is not read_only:
        raise ContractError(f"candidate read-only mode drifted at {target}")
    volume = item.get("volume") or {}
    if volume.get("subpath") != subpath:
        raise ContractError(f"candidate subpath drifted at {target}")


def validate(root: Path, env_file: Path) -> dict[str, Any]:
    root = root.resolve()
    dashboard = root / "web-dashboard"
    env_file = env_file.resolve()
    contract_path = root / "docs/project/receipts/FR-06C3C1-backup-operations-overlay-contract.json"
    contract = _json(contract_path)
    accepted_files = [dashboard / name for name in contract["accepted_compose_files"]]
    candidate_files = [dashboard / name for name in contract["candidate_compose_files"]]
    for path in [env_file, contract_path, *candidate_files]:
        if not path.is_file():
            raise ContractError(f"required source is missing: {path}")
    accepted = _render(dashboard, env_file, accepted_files)
    candidate = _render(dashboard, env_file, candidate_files)
    before_services = accepted.get("services") or {}
    after_services = candidate.get("services") or {}
    if set(before_services) != set(after_services):
        raise ContractError("C3 overlays changed service set")

    backup = contract["local_backup"]
    backup_target = backup["target"]
    for name, mode in backup["consumers"].items():
        before = _mount(before_services[name], backup_target)
        if before.get("source") != backup["legacy_compose_volume"]:
            raise ContractError(f"accepted backup mount drifted for {name}")
        _assert_candidate_mount(
            after_services[name], backup_target, backup["candidate_compose_volume"], backup["candidate_subpath"], mode == "ro"
        )

    ops = contract["operations"]
    before_redis = _mount(before_services["redis"], ops["target"])
    if before_redis.get("source") != ops["legacy_redis_compose_volume"]:
        raise ContractError("accepted Redis mount drifted")
    _assert_candidate_mount(after_services["redis"], ops["target"], ops["candidate_compose_volume"], ops["candidate_subpath"], False)
    if after_services["redis"].get("restart") != "no":
        raise ContractError("Redis is not guarded with restart:no")
    for name in backup["consumers"]:
        if after_services[name].get("restart") != "no":
            raise ContractError(f"{name} lost existing guarded restart:no policy")

    forbidden = {backup["legacy_compose_volume"], ops["legacy_redis_compose_volume"]}
    for service, definition in after_services.items():
        for item in _mounts(definition):
            if item.get("source") in forbidden:
                raise ContractError(f"legacy C3 protected volume remains mounted by {service}")

    after_volumes = candidate.get("volumes") or {}
    for logical, external in (
        (backup["candidate_compose_volume"], backup["candidate_docker_volume"]),
        (ops["candidate_compose_volume"], ops["candidate_docker_volume"]),
    ):
        definition = after_volumes.get(logical)
        if not isinstance(definition, dict) or definition.get("external") is not True or definition.get("name") != external:
            raise ContractError(f"external volume definition drifted for {logical}")

    targets = {"backend": backup_target, "backup-worker": backup_target, "redis": ops["target"]}
    for name in before_services:
        before = _strip_target(before_services[name], targets.get(name), ignore_restart=(name == "redis"))
        after = _strip_target(after_services[name], targets.get(name), ignore_restart=(name == "redis"))
        if before != after:
            raise ContractError(f"C3 overlays changed unrelated service configuration: {name}")

    before_top = copy.deepcopy(accepted)
    after_top = copy.deepcopy(candidate)
    before_top.pop("services", None)
    after_top.pop("services", None)
    before_volumes = before_top.pop("volumes", {}) or {}
    candidate_volumes = after_top.pop("volumes", {}) or {}
    # Compose omits now-unused legacy volume declarations from the rendered
    # candidate after their final consumers move to the external vaults. The
    # base source declarations remain untouched for rollback, so exclude only
    # these two intentionally unreferenced legacy definitions from comparison.
    before_volumes.pop(backup["legacy_compose_volume"], None)
    before_volumes.pop(ops["legacy_redis_compose_volume"], None)
    candidate_volumes.pop(backup["candidate_compose_volume"], None)
    candidate_volumes.pop(ops["candidate_compose_volume"], None)
    if before_top != after_top or before_volumes != candidate_volumes:
        raise ContractError("C3 overlays changed unrelated top-level configuration")

    return {
        "schema_version": 1,
        "subpart": "FR-06C3C1",
        "validation": "FR06C3_BACKUP_OPERATIONS_OVERLAY_PASS",
        "env_profile": env_file.name,
        "legacy_backup_mounts_after_candidate": 0,
        "legacy_redis_mounts_after_candidate": 0,
        "redis_restart_policy": "no",
        "backup_consumers_guarded": True,
        "unrelated_service_or_top_level_drift": False,
        "production_changed": False,
        "contract_sha256": _sha(contract_path),
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
        print(f"FR06C3_OVERLAY_FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(value, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
