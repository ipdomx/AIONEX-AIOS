#!/usr/bin/env python3
"""Validate the FR-06B2 source-only Compose overlay without starting Docker services."""

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
    """Raised when the rendered Compose topology diverges from the retained contract."""


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ContractError(f"{path.name} must contain a JSON object")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _compose_json(
    dashboard: Path,
    env_file: Path,
    compose_files: list[Path],
) -> dict[str, Any]:
    command = [
        "docker",
        "compose",
        "--env-file",
        str(env_file),
        "--profile",
        "*",
    ]
    for path in compose_files:
        command.extend(["-f", str(path)])
    command.extend(["config", "--format", "json"])
    environment = os.environ.copy()
    environment["AIOS_ENV_FILE"] = str(env_file)
    result = subprocess.run(
        command,
        cwd=dashboard,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=90,
    )
    if result.returncode != 0:
        raise ContractError(
            f"docker compose config failed for {len(compose_files)} file(s) "
            f"with exit code {result.returncode}; output is withheld because "
            "rendered configuration may contain secrets"
        )
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ContractError("docker compose did not return valid JSON") from exc
    if not isinstance(value, dict):
        raise ContractError("rendered Compose configuration must be an object")
    return value


def _expected_mounts(contract: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    roots = contract["matrix"]["roots"]
    expected: dict[tuple[str, str], dict[str, Any]] = {}
    for root in roots:
        for consumer in root["consumers"]:
            key = (consumer["service"], consumer["target"])
            if key in expected:
                raise ContractError(f"duplicate contract target: {key}")
            expected[key] = {
                "legacy_source": root["compose_volume"],
                "overlay_source": root["overlay_volume"],
                "subpath": root["target_subpath"],
                "read_only": consumer["access"] == "ro",
            }
    declared_count = int(contract["matrix"]["protected_mount_count"])
    if len(expected) != declared_count:
        raise ContractError(
            f"contract declares {declared_count} mounts but defines {len(expected)}"
        )
    return expected


def _volume_mounts(config: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    services = config.get("services", {})
    if not isinstance(services, dict):
        raise ContractError("rendered services must be an object")
    for service, definition in services.items():
        if not isinstance(definition, dict):
            raise ContractError(f"rendered service {service} must be an object")
        for mount in definition.get("volumes", []) or []:
            if isinstance(mount, dict):
                records.append({"service": service, **mount})
    return records


def _assert_base_matrix(
    base_config: dict[str, Any],
    expected: dict[tuple[str, str], dict[str, Any]],
) -> None:
    legacy_sources = {item["legacy_source"] for item in expected.values()}
    actual: dict[tuple[str, str], dict[str, Any]] = {}
    for mount in _volume_mounts(base_config):
        if mount.get("source") not in legacy_sources:
            continue
        key = (str(mount["service"]), str(mount.get("target", "")))
        if key in actual:
            raise ContractError(f"duplicate rendered legacy target: {key}")
        actual[key] = mount
    if set(actual) != set(expected):
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        raise ContractError(
            f"base consumer matrix drifted; missing={missing!r}, extra={extra!r}"
        )
    for key, wanted in expected.items():
        mount = actual[key]
        if mount.get("type") != "volume":
            raise ContractError(f"base protected target is not a volume: {key}")
        if mount.get("source") != wanted["legacy_source"]:
            raise ContractError(f"base source drifted for {key}")
        if bool(mount.get("read_only", False)) != wanted["read_only"]:
            raise ContractError(f"base access mode drifted for {key}")


def _assert_overlay_matrix(
    merged_config: dict[str, Any],
    expected: dict[tuple[str, str], dict[str, Any]],
) -> None:
    mounts = _volume_mounts(merged_config)
    legacy_sources = {item["legacy_source"] for item in expected.values()}
    overlay_sources = {item["overlay_source"] for item in expected.values()}
    if any(mount.get("source") in legacy_sources for mount in mounts):
        raise ContractError("a legacy protected volume remains mounted after overlay merge")

    by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for mount in mounts:
        key = (str(mount["service"]), str(mount.get("target", "")))
        if key in expected:
            by_key.setdefault(key, []).append(mount)
        elif mount.get("source") in overlay_sources:
            raise ContractError(f"vault mounted outside the approved matrix: {key}")

    if set(by_key) != set(expected):
        missing = sorted(set(expected) - set(by_key))
        extra = sorted(set(by_key) - set(expected))
        raise ContractError(
            f"overlay consumer matrix drifted; missing={missing!r}, extra={extra!r}"
        )

    for key, wanted in expected.items():
        matches = by_key[key]
        if len(matches) != 1:
            raise ContractError(f"expected exactly one rendered mount for {key}")
        mount = matches[0]
        if mount.get("type") != "volume":
            raise ContractError(f"overlay protected target is not a volume: {key}")
        if mount.get("source") != wanted["overlay_source"]:
            raise ContractError(f"overlay source drifted for {key}")
        if bool(mount.get("read_only", False)) != wanted["read_only"]:
            raise ContractError(f"overlay access mode drifted for {key}")
        volume_options = mount.get("volume") or {}
        if volume_options.get("subpath") != wanted["subpath"]:
            raise ContractError(f"overlay subpath drifted for {key}")


def _service_without_protected_mounts(
    config: dict[str, Any],
    service: str,
    expected: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    definition = copy.deepcopy(config["services"][service])
    mounts = definition.get("volumes", []) or []
    definition["volumes"] = [
        mount
        for mount in mounts
        if not (
            isinstance(mount, dict)
            and (service, str(mount.get("target", ""))) in expected
        )
    ]
    return definition


def _assert_no_unrelated_drift(
    base_config: dict[str, Any],
    merged_config: dict[str, Any],
    expected: dict[tuple[str, str], dict[str, Any]],
) -> None:
    base_services = base_config.get("services", {})
    merged_services = merged_config.get("services", {})
    if set(base_services) != set(merged_services):
        raise ContractError("overlay changed the service set")
    for service in base_services:
        if _service_without_protected_mounts(
            base_config, service, expected
        ) != _service_without_protected_mounts(merged_config, service, expected):
            raise ContractError(f"overlay changed unrelated service configuration: {service}")

    def top_level(value: dict[str, Any]) -> dict[str, Any]:
        result = copy.deepcopy(value)
        result.pop("services", None)
        result.pop("volumes", None)
        return result

    if top_level(base_config) != top_level(merged_config):
        raise ContractError("overlay changed unrelated top-level configuration")

    base_volumes = base_config.get("volumes", {})
    merged_volumes = merged_config.get("volumes", {})
    legacy_sources = {item["legacy_source"] for item in expected.values()}
    for name, definition in base_volumes.items():
        if name not in merged_volumes:
            if name in legacy_sources:
                continue
            raise ContractError(f"overlay removed unrelated base volume key: {name}")
        rendered = merged_volumes[name]
        # Compose prunes declared-but-unused protected volumes after every consumer
        # is replaced. The reviewed base file still retains those definitions for
        # rollback; all remaining rendered base definitions must stay unchanged.
        if rendered != definition and not (
            name in legacy_sources and rendered is None
        ):
            raise ContractError(f"overlay changed retained base volume definition: {name}")

    expected_new = {
        "fr06_asset_vault": "aionex-fr06-asset-vault",
        "fr06_project_execution_vault": "aionex-fr06-project-execution-vault",
    }
    if set(merged_volumes) - set(base_volumes) != set(expected_new):
        raise ContractError("overlay introduced an unexpected top-level volume")
    for logical_name, external_name in expected_new.items():
        definition = merged_volumes[logical_name]
        if definition.get("external") is not True:
            raise ContractError(f"{logical_name} must remain external")
        if definition.get("name") != external_name:
            raise ContractError(f"{logical_name} external name drifted")


def validate(root: Path, env_file: Path) -> dict[str, Any]:
    root = root.resolve()
    env_file = env_file.resolve()
    dashboard = root / "web-dashboard"
    base_path = dashboard / "docker-compose.production.yml"
    overlay_path = dashboard / "docker-compose.fr06-assets.yml"
    contract_path = (
        root
        / "docs"
        / "project"
        / "receipts"
        / "FR-06B2-compose-cutover-contract.json"
    )
    for path in (env_file, base_path, overlay_path, contract_path):
        if not path.is_file():
            raise ContractError(f"required file is missing: {path}")

    contract = _load_json(contract_path)
    expected = _expected_mounts(contract)
    base_config = _compose_json(dashboard, env_file, [base_path])
    merged_config = _compose_json(dashboard, env_file, [base_path, overlay_path])
    _assert_base_matrix(base_config, expected)
    _assert_overlay_matrix(merged_config, expected)
    _assert_no_unrelated_drift(base_config, merged_config, expected)

    version = subprocess.run(
        ["docker", "compose", "version", "--short"],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    compose_version = version.stdout.strip() if version.returncode == 0 else "unknown"
    return {
        "schema_version": 1,
        "subpart": "FR-06B2",
        "validation": "FR06B2_COMPOSE_OVERLAY_PASS",
        "compose_version": compose_version,
        "env_profile": env_file.name,
        "compose_profile_scope": "*",
        "base_compose_sha256": _sha256(base_path),
        "overlay_sha256": _sha256(overlay_path),
        "contract_sha256": _sha256(contract_path),
        "validator_sha256": _sha256(Path(__file__).resolve()),
        "protected_root_count": int(contract["matrix"]["root_count"]),
        "protected_mount_count": len(expected),
        "affected_service_definition_count": len(
            {service for service, _target in expected}
        ),
        "legacy_protected_mounts_after_merge": 0,
        "unrelated_service_or_top_level_drift": False,
        "docker_daemon_or_service_start_required": False,
        "production_changed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    parser.add_argument("--env-file", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    env_file = args.env_file or (
        root / "web-dashboard" / ".env.production.example"
    )
    try:
        result = validate(root, env_file)
    except (ContractError, OSError, subprocess.SubprocessError) as exc:
        print(f"FR06B2_COMPOSE_OVERLAY_FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
