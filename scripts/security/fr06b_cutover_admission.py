#!/usr/bin/env python3
"""Fail-closed FR-06B3A runtime inspection and cutover admission evaluator."""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


class AdmissionError(RuntimeError):
    """Malformed input or an operational inspection failure."""


class AdmissionBlocked(RuntimeError):
    """Well-formed evidence that does not satisfy every admission gate."""


SHA_RE = re.compile(r"^[0-9a-f]{40}$")
REFERENCE_RE = re.compile(r"^[a-z][a-z0-9+.-]*://[^\s]+$")
LOCAL_SCHEMES = {"file", "host", "lab", "local", "tmpfs"}
PRODUCTION_KEY_SCHEMES = {"aws-kms", "gcp-kms", "hsm", "kms", "offline", "vault"}
PRODUCTION_HEADER_SCHEMES = {"escrow", "r2", "s3", "vault"}
PRODUCTION_ALERT_SCHEMES = {"opsgenie", "pagerduty", "receipt", "ticket"}
SENSITIVE_KEYS = {
    "key", "key_bytes", "key_material", "passphrase", "password", "plaintext_key",
    "private_key", "recovery_key", "secret", "secret_key", "token",
}


def _json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AdmissionError(f"cannot read valid JSON object: {path}") from exc
    if not isinstance(value, dict):
        raise AdmissionError(f"JSON object required: {path}")
    return value


def _run(command: list[str], *, cwd: Path | None = None, timeout: int = 30) -> str:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise AdmissionError(f"command unavailable: {command[0]}") from exc
    if result.returncode != 0:
        raise AdmissionError(
            f"{command[0]} inspection failed with exit code {result.returncode}; "
            "command output withheld"
        )
    return result.stdout.strip()


def _parse_time(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise AdmissionError(f"{label} must be an RFC3339 UTC timestamp")
    if not value.endswith("Z"):
        raise AdmissionError(f"{label} must use UTC Z form")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise AdmissionError(f"{label} is not a valid timestamp") from exc
    if parsed.tzinfo is None:
        raise AdmissionError(f"{label} must be timezone aware")
    return parsed.astimezone(timezone.utc)


def _age_seconds(value: Any, now: datetime, label: str) -> float:
    observed = _parse_time(value, label)
    age = (now - observed).total_seconds()
    if age < -300:
        raise AdmissionBlocked(f"{label} is more than five minutes in the future")
    return max(age, 0.0)


def _walk_sensitive(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).casefold().replace("-", "_")
            if normalized in SENSITIVE_KEYS or normalized.endswith("_key_material"):
                raise AdmissionError(f"embedded secret material field rejected at {path}.{key}")
            _walk_sensitive(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _walk_sensitive(child, f"{path}[{index}]")


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AdmissionError(f"{label} must be an object")
    return value


def _truth(value: Any, label: str, blockers: list[str]) -> None:
    if value is not True:
        blockers.append(label)


def _reference(value: Any, label: str, blockers: list[str], schemes: set[str] | None = None) -> str:
    if not isinstance(value, str) or not REFERENCE_RE.fullmatch(value):
        blockers.append(f"{label}:invalid_reference")
        return ""
    scheme = value.split("://", 1)[0].casefold()
    if scheme in LOCAL_SCHEMES:
        blockers.append(f"{label}:local_reference_forbidden")
    if schemes is not None and scheme not in schemes:
        blockers.append(f"{label}:unsupported_scheme")
    return value


def _load_b2(root: Path):
    module_path = root / "scripts" / "security" / "fr06b_validate_compose_overlay.py"
    spec = importlib.util.spec_from_file_location("fr06b2_validator", module_path)
    if spec is None or spec.loader is None:
        raise AdmissionError("cannot load FR-06B2 validator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_restart_overlay(root: Path, env_file: Path) -> dict[str, Any]:
    b2 = _load_b2(root)
    try:
        b2_result = b2.validate(root, env_file)
    except Exception as exc:
        raise AdmissionError("FR-06B2 overlay validation failed; detail withheld") from exc
    dashboard = root / "web-dashboard"
    base = dashboard / "docker-compose.production.yml"
    assets = dashboard / "docker-compose.fr06-assets.yml"
    restart = dashboard / "docker-compose.fr06-admission.yml"
    contract = _json_object(
        root / "docs" / "project" / "receipts" / "FR-06B2-compose-cutover-contract.json"
    )
    if not restart.is_file():
        raise AdmissionError("FR-06B3A admission overlay is missing")
    guarded = sorted(
        set(contract["matrix"]["runtime_writer_services"])
        | set(contract["matrix"]["read_only_only_services"])
    )
    initializers = sorted(contract["matrix"]["initializer_services"])
    before = b2._compose_json(dashboard, env_file, [base, assets])
    after = b2._compose_json(dashboard, env_file, [base, assets, restart])
    if set(before.get("services", {})) != set(after.get("services", {})):
        raise AdmissionError("restart overlay changed the service set")
    if {k: v for k, v in before.items() if k != "services"} != {
        k: v for k, v in after.items() if k != "services"
    }:
        raise AdmissionError("restart overlay changed top-level configuration")
    changed: list[str] = []
    for service, prior_definition in before["services"].items():
        next_definition = after["services"][service]
        prior_without = copy.deepcopy(prior_definition)
        next_without = copy.deepcopy(next_definition)
        prior_restart = prior_without.pop("restart", None)
        next_restart = next_without.pop("restart", None)
        if prior_without != next_without:
            raise AdmissionError(f"restart overlay changed unrelated configuration: {service}")
        if service in guarded:
            if prior_restart != "unless-stopped":
                raise AdmissionError(f"unexpected base restart policy: {service}")
            if next_restart != "no":
                raise AdmissionError(f"guarded restart policy missing: {service}")
            changed.append(service)
        elif next_restart != prior_restart:
            raise AdmissionError(f"restart overlay changed an unscoped service: {service}")
    for service in initializers:
        if before["services"][service].get("restart") != "no":
            raise AdmissionError(f"initializer base policy drifted: {service}")
        if after["services"][service].get("restart") != "no":
            raise AdmissionError(f"initializer policy changed: {service}")
    if sorted(changed) != guarded or len(guarded) != 20:
        raise AdmissionError("guarded restart service matrix drifted")
    return {
        "fr06b2_validation": b2_result["validation"],
        "restart_validation": "FR06B3A_RESTART_OVERLAY_PASS",
        "guarded_restart_policy": "no",
        "guarded_service_count": len(guarded),
        "initializer_service_count": len(initializers),
        "all_profiles": True,
    }


def _mount_snapshot(root: Path, mapper: Path, role: str, subpaths: Iterable[str]) -> dict[str, Any]:
    if not root.is_absolute() or not mapper.is_absolute():
        raise AdmissionError(f"{role} paths must be absolute")
    try:
        mapper_info = os.stat(mapper)
    except OSError as exc:
        raise AdmissionBlocked(f"{role}:mapper_missing") from exc
    if not stat.S_ISBLK(mapper_info.st_mode):
        raise AdmissionBlocked(f"{role}:mapper_not_block_device")
    mapper_name = mapper.name
    status_output = _run(["cryptsetup", "status", mapper_name])
    if " is active" not in status_output:
        raise AdmissionBlocked(f"{role}:mapper_not_active")
    fs_type = _run(["blkid", "-o", "value", "-s", "TYPE", str(mapper)])
    if fs_type != "ext4":
        raise AdmissionBlocked(f"{role}:filesystem_not_ext4")
    line = _run(["findmnt", "-n", "-o", "SOURCE,FSTYPE,OPTIONS", "--target", str(root)])
    pieces = line.split(None, 2)
    if len(pieces) != 3:
        raise AdmissionError(f"{role}:cannot_parse_mount")
    source, mounted_type, option_text = pieces
    options = sorted(set(option_text.split(",")))
    if os.path.realpath(source) != os.path.realpath(mapper):
        raise AdmissionBlocked(f"{role}:mount_source_mismatch")
    if mounted_type != "ext4":
        raise AdmissionBlocked(f"{role}:mount_filesystem_not_ext4")
    required = {"nodev", "nosuid"} | ({"noexec"} if role == "asset-vault" else set())
    forbidden = set() if role == "asset-vault" else {"noexec"}
    missing_options = sorted(required - set(options))
    forbidden_present = sorted(forbidden & set(options))
    if missing_options:
        raise AdmissionBlocked(f"{role}:missing_mount_options:{','.join(missing_options)}")
    if forbidden_present:
        raise AdmissionBlocked(f"{role}:forbidden_mount_options:{','.join(forbidden_present)}")
    missing_subpaths: list[str] = []
    for name in subpaths:
        candidate = root / name
        try:
            info = os.lstat(candidate)
        except OSError:
            missing_subpaths.append(name)
            continue
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            missing_subpaths.append(name)
    if missing_subpaths:
        raise AdmissionBlocked(f"{role}:missing_or_unsafe_subpaths:{','.join(missing_subpaths)}")
    return {
        "role": role,
        "path": str(mapper),
        "active": True,
        "block_device": True,
        "filesystem": fs_type,
        "mount_root": str(root),
        "mount_source_matches": True,
        "mount_options": options,
        "required_options_present": True,
        "forbidden_options_absent": True,
        "subpaths_present": sorted(subpaths),
    }


def _docker_volume_snapshot(
    docker_host: str,
    name: str,
    mapper: Path,
    role: str,
) -> dict[str, Any]:
    value = json.loads(_run(["docker", "--host", docker_host, "volume", "inspect", name]))
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        raise AdmissionError(f"{role}:unexpected Docker volume inspection")
    item = value[0]
    if item.get("Driver") != "local":
        raise AdmissionBlocked(f"{role}:volume_driver_not_local")
    options = item.get("Options")
    if not isinstance(options, dict):
        raise AdmissionBlocked(f"{role}:volume_options_missing")
    raw_options = str(options.get("o", ""))
    actual_options = set(raw_options.split(",")) if raw_options else set()
    required = {"nodev", "nosuid"} | ({"noexec"} if role == "asset-vault" else set())
    forbidden = set() if role == "asset-vault" else {"noexec"}
    if options.get("type") != "ext4":
        raise AdmissionBlocked(f"{role}:volume_type_not_ext4")
    if os.path.realpath(str(options.get("device", ""))) != os.path.realpath(mapper):
        raise AdmissionBlocked(f"{role}:volume_device_mismatch")
    if actual_options != required:
        missing = sorted(required - actual_options)
        extra = sorted(actual_options - required)
        raise AdmissionBlocked(
            f"{role}:volume_options_not_exact:missing={','.join(missing)}:"
            f"extra={','.join(extra)}"
        )
    if forbidden & actual_options:
        raise AdmissionBlocked(f"{role}:volume_forbidden_options")
    running_ids = [
        line for line in _run(
            ["docker", "--host", docker_host, "ps", "--filter", f"volume={name}", "--format", "{{.ID}}"]
        ).splitlines() if line
    ]
    if running_ids:
        raise AdmissionBlocked(f"{role}:running_volume_consumers")
    return {
        "role": role,
        "name": name,
        "driver": "local",
        "device": str(mapper),
        "type": "ext4",
        "options": sorted(actual_options),
        "running_consumer_count": 0,
    }


def inspect_runtime(args: argparse.Namespace) -> dict[str, Any]:
    root = args.root.resolve()
    env_file = args.env_file.resolve()
    contract = _json_object(
        root / "docs" / "project" / "receipts" / "FR-06B2-compose-cutover-contract.json"
    )
    roots = contract["matrix"]["roots"]
    asset_subpaths = [
        item["target_subpath"] for item in roots if item["vault"] == "asset-vault"
    ]
    project_subpaths = [
        item["target_subpath"]
        for item in roots
        if item["vault"] == "project-execution-vault"
    ]
    compose = validate_restart_overlay(root, env_file)
    mappers = [
        _mount_snapshot(args.asset_mount_root.resolve(), args.asset_mapper, "asset-vault", asset_subpaths),
        _mount_snapshot(
            args.project_mount_root.resolve(),
            args.project_mapper,
            "project-execution-vault",
            project_subpaths,
        ),
    ]
    volumes = [
        _docker_volume_snapshot(
            args.docker_host, args.asset_volume, args.asset_mapper, "asset-vault"
        ),
        _docker_volume_snapshot(
            args.docker_host,
            args.project_volume,
            args.project_mapper,
            "project-execution-vault",
        ),
    ]
    return {
        "schema_version": 1,
        "subpart": "FR-06B3A",
        "validation": "FR06B3A_RUNTIME_SNAPSHOT_PASS",
        "environment": args.environment,
        "observed_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "docker_host": args.docker_host,
        "mappers": mappers,
        "volumes": volumes,
        "compose": compose,
        "read_only_inspection": True,
        "containers_started_or_created": False,
        "vaults_mounted_or_unlocked": False,
    }


def evaluate(
    evidence: dict[str, Any],
    snapshot: dict[str, Any],
    allow_isolated_lab: bool,
    max_age: int,
) -> dict[str, Any]:
    _walk_sensitive(evidence)
    _walk_sensitive(snapshot)
    if evidence.get("schema_version") != 1:
        raise AdmissionError("evidence.schema_version must be 1")
    if snapshot.get("schema_version") != 1:
        raise AdmissionError("snapshot.schema_version must be 1")
    if snapshot.get("subpart") != "FR-06B3A":
        raise AdmissionError("snapshot.subpart must be FR-06B3A")

    blockers: list[str] = []
    environment = evidence.get("environment")
    if environment not in {"isolated_lab", "production"}:
        raise AdmissionError("evidence.environment must be isolated_lab or production")
    if snapshot.get("environment") != environment:
        blockers.append("environment_mismatch")
    if snapshot.get("validation") != "FR06B3A_RUNTIME_SNAPSHOT_PASS":
        blockers.append("runtime_snapshot_validation")
    if snapshot.get("read_only_inspection") is not True:
        blockers.append("runtime_snapshot_not_read_only")
    if snapshot.get("containers_started_or_created") is not False:
        blockers.append("runtime_inspection_started_or_created_containers")
    if snapshot.get("vaults_mounted_or_unlocked") is not False:
        blockers.append("runtime_inspection_mounted_or_unlocked_vaults")

    compose = _mapping(snapshot.get("compose"), "snapshot.compose")
    expected_compose = {
        "fr06b2_validation": "FR06B2_COMPOSE_OVERLAY_PASS",
        "restart_validation": "FR06B3A_RESTART_OVERLAY_PASS",
        "guarded_restart_policy": "no",
        "guarded_service_count": 20,
        "initializer_service_count": 2,
        "all_profiles": True,
    }
    for key, expected in expected_compose.items():
        if compose.get(key) != expected:
            blockers.append(f"compose:{key}")

    expected_subpaths = {
        "asset-vault": {
            "three_d_asset_data",
            "media_asset_data",
            "studio_asset_data",
            "course_package_data",
            "realtime_recording_data",
            "portal_asset_data",
            "mobile_release_data",
            "audio_song_ingress_data",
            "security_source_data",
            "security_remediation_data",
        },
        "project-execution-vault": {"project_execution_data"},
    }
    expected_options = {
        "asset-vault": {"nodev", "nosuid", "noexec"},
        "project-execution-vault": {"nodev", "nosuid"},
    }
    production_mappers = {
        "asset-vault": "/dev/mapper/aionex-asset-vault",
        "project-execution-vault": "/dev/mapper/aionex-project-execution-vault",
    }
    production_volumes = {
        "asset-vault": "aionex-fr06-asset-vault",
        "project-execution-vault": "aionex-fr06-project-execution-vault",
    }

    mappers = snapshot.get("mappers")
    if not isinstance(mappers, list) or len(mappers) != 2:
        blockers.append("mapper_snapshot_count")
        mapper_by_role: dict[str, dict[str, Any]] = {}
    else:
        mapper_by_role = {
            str(item.get("role")): item for item in mappers if isinstance(item, dict)
        }
        if set(mapper_by_role) != set(expected_subpaths) or len(mapper_by_role) != len(mappers):
            blockers.append("mapper_role_matrix")
        for role, wanted_subpaths in expected_subpaths.items():
            item = mapper_by_role.get(role)
            if item is None:
                continue
            for key in (
                "active",
                "block_device",
                "mount_source_matches",
                "required_options_present",
                "forbidden_options_absent",
            ):
                _truth(item.get(key), f"{role}:{key}", blockers)
            if item.get("filesystem") != "ext4":
                blockers.append(f"{role}:filesystem")
            path = item.get("path")
            if not isinstance(path, str) or not path.startswith("/dev/mapper/"):
                blockers.append(f"{role}:mapper_path")
            if environment == "production" and path != production_mappers[role]:
                blockers.append(f"{role}:production_mapper_path")
            mount_options = item.get("mount_options")
            if not isinstance(mount_options, list):
                blockers.append(f"{role}:mount_options_shape")
            else:
                observed_options = {str(value) for value in mount_options}
                if not expected_options[role].issubset(observed_options):
                    blockers.append(f"{role}:mount_options")
                if role == "project-execution-vault" and "noexec" in observed_options:
                    blockers.append(f"{role}:forbidden_noexec")
            subpaths = item.get("subpaths_present")
            if not isinstance(subpaths, list) or {str(value) for value in subpaths} != wanted_subpaths:
                blockers.append(f"{role}:subpath_matrix")

    volumes = snapshot.get("volumes")
    if not isinstance(volumes, list) or len(volumes) != 2:
        blockers.append("volume_snapshot_count")
        volume_by_role: dict[str, dict[str, Any]] = {}
    else:
        volume_by_role = {
            str(item.get("role")): item for item in volumes if isinstance(item, dict)
        }
        if set(volume_by_role) != set(expected_options) or len(volume_by_role) != len(volumes):
            blockers.append("volume_role_matrix")
        for role, wanted_options in expected_options.items():
            item = volume_by_role.get(role)
            if item is None:
                continue
            if item.get("driver") != "local":
                blockers.append(f"{role}:volume_driver")
            if item.get("type") != "ext4":
                blockers.append(f"{role}:volume_type")
            if item.get("running_consumer_count") != 0:
                blockers.append(f"{role}:running_consumers")
            options = item.get("options")
            if not isinstance(options, list) or {str(value) for value in options} != wanted_options:
                blockers.append(f"{role}:volume_options")
            device = item.get("device")
            if not isinstance(device, str) or not device.startswith("/dev/mapper/"):
                blockers.append(f"{role}:volume_device")
            if environment == "production":
                if item.get("name") != production_volumes[role]:
                    blockers.append(f"{role}:production_volume_name")
                if device != production_mappers[role]:
                    blockers.append(f"{role}:production_volume_device")

    docker_host = snapshot.get("docker_host")
    if not isinstance(docker_host, str) or not docker_host.startswith("unix://"):
        blockers.append("docker_host_must_be_unix_socket")
    if environment == "production" and docker_host not in {
        "unix:///run/docker.sock",
        "unix:///var/run/docker.sock",
    }:
        blockers.append("production_docker_host")

    now = datetime.now(timezone.utc)
    try:
        if _age_seconds(snapshot.get("observed_at"), now, "snapshot.observed_at") > max_age:
            blockers.append("runtime_snapshot_stale")
        if _age_seconds(evidence.get("observed_at"), now, "evidence.observed_at") > max_age:
            blockers.append("evidence_stale")
    except AdmissionBlocked as exc:
        blockers.append(str(exc))

    safety = _mapping(evidence.get("safety"), "evidence.safety")
    for key in (
        "docker_restart_rehearsal_passed",
        "missing_mapper_rehearsal_passed",
        "wrong_key_rehearsal_passed",
        "delayed_unlock_rehearsal_passed",
        "pre_admission_rollback_passed",
        "post_admission_reverse_delta_rollback_passed",
    ):
        _truth(safety.get(key), f"safety:{key}", blockers)

    operations = _mapping(evidence.get("operations"), "evidence.operations")
    _truth(operations.get("admission_closed"), "operations:admission_closed", blockers)
    if operations.get("cloudflare_changed") is not False:
        blockers.append("operations:cloudflare_must_remain_unchanged")

    source = _mapping(evidence.get("source"), "evidence.source")
    if environment == "isolated_lab":
        # A disposable rehearsal can truthfully prove the complete lifecycle
        # before admission. Production preflight cannot: the guarded executor
        # performs these mutable steps only after it consumes its one-time plan.
        for key in (
            "queues_drained",
            "writers_stopped",
            "initializers_stopped",
            "read_only_consumers_stopped",
            "no_unlisted_writable_descriptors",
            "final_delta_exact",
        ):
            _truth(operations.get(key), f"operations:{key}", blockers)
        if not allow_isolated_lab:
            blockers.append("isolated_lab_requires_explicit_flag")
        if evidence.get("production_authorization") is not False:
            blockers.append("isolated_lab_must_deny_production_authorization")
        if not isinstance(source.get("lab_commit_sha"), str) or not SHA_RE.fullmatch(
            source["lab_commit_sha"]
        ):
            blockers.append("source:lab_commit_sha")
    else:
        if evidence.get("production_authorization") is not True:
            blockers.append("production_authorization")
        for key in ("pr_head_sha", "merge_sha"):
            if not isinstance(source.get(key), str) or not SHA_RE.fullmatch(source[key]):
                blockers.append(f"source:{key}")
        _truth(
            source.get("protected_pr_checks_passed"),
            "source:protected_pr_checks_passed",
            blockers,
        )
        _truth(
            source.get("post_merge_main_checks_passed"),
            "source:post_merge_main_checks_passed",
            blockers,
        )
        _truth(
            safety.get("out_of_band_alert_passed"),
            "safety:out_of_band_alert_passed",
            blockers,
        )
        baseline = operations.get("baseline_p95_ms")
        if (
            not isinstance(baseline, (int, float))
            or isinstance(baseline, bool)
            or baseline <= 0
        ):
            blockers.append("operations:baseline_p95_ms")
        if "candidate_p95_ms" in operations:
            blockers.append("operations:candidate_p95_ms_is_post_cutover")
        for key in (
            "queues_drained",
            "writers_stopped",
            "initializers_stopped",
            "read_only_consumers_stopped",
            "no_unlisted_writable_descriptors",
            "final_delta_exact",
        ):
            if key in operations:
                blockers.append(f"operations:{key}:premature_preflight_claim")

        approvals = _mapping(evidence.get("approvals"), "evidence.approvals")
        _truth(
            approvals.get("owner_authorized"),
            "approvals:owner_authorized",
            blockers,
        )
        _reference(
            approvals.get("maintenance_window_ref"),
            "approvals:maintenance_window_ref",
            blockers,
        )
        recovery = _mapping(evidence.get("recovery"), "evidence.recovery")
        r2 = _mapping(
            recovery.get("encrypted_r2_restore"),
            "evidence.recovery.encrypted_r2_restore",
        )
        _truth(r2.get("passed"), "recovery:encrypted_r2_restore", blockers)
        _reference(
            r2.get("ref"),
            "recovery:r2_restore_ref",
            blockers,
            {"r2", "receipt"},
        )
        try:
            if _age_seconds(
                r2.get("observed_at"), now, "recovery.r2.observed_at"
            ) > max_age:
                blockers.append("recovery:r2_restore_stale")
        except AdmissionBlocked as exc:
            blockers.append(str(exc))
        active_ref = _reference(
            recovery.get("active_key_ref"),
            "recovery:active_key_ref",
            blockers,
            PRODUCTION_KEY_SCHEMES,
        )
        recovery_ref = _reference(
            recovery.get("recovery_key_ref"),
            "recovery:recovery_key_ref",
            blockers,
            PRODUCTION_KEY_SCHEMES,
        )
        asset_header = _reference(
            recovery.get("asset_header_ref"),
            "recovery:asset_header_ref",
            blockers,
            PRODUCTION_HEADER_SCHEMES,
        )
        project_header = _reference(
            recovery.get("project_header_ref"),
            "recovery:project_header_ref",
            blockers,
            PRODUCTION_HEADER_SCHEMES,
        )
        _truth(
            recovery.get("custody_independent"),
            "recovery:custody_independent",
            blockers,
        )
        _truth(
            recovery.get("headers_separate_from_recovery_key"),
            "recovery:headers_separate_from_recovery_key",
            blockers,
        )
        refs = [active_ref, recovery_ref, asset_header, project_header]
        if all(refs) and len(set(refs)) != len(refs):
            blockers.append("recovery:custody_references_not_distinct")
        _reference(
            safety.get("out_of_band_alert_ref"),
            "safety:out_of_band_alert_ref",
            blockers,
            PRODUCTION_ALERT_SCHEMES,
        )

    ready_decision = (
        "isolated_lab_ready"
        if environment == "isolated_lab"
        else "production_preflight_ready"
    )
    return {
        "schema_version": 1,
        "subpart": "FR-06B3A",
        "environment": environment,
        "decision": ready_decision if not blockers else "blocked",
        "preflight_passed": not blockers,
        "production_authorized": False,
        "executor_present": False,
        "blockers": sorted(set(blockers)),
        "evaluated_at": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
    }

def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    commands = value.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect-runtime")
    inspect.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    inspect.add_argument("--env-file", type=Path, required=True)
    inspect.add_argument("--docker-host", required=True)
    inspect.add_argument("--environment", choices=("isolated_lab", "production"), required=True)
    inspect.add_argument("--asset-mapper", type=Path, required=True)
    inspect.add_argument("--project-mapper", type=Path, required=True)
    inspect.add_argument("--asset-mount-root", type=Path, required=True)
    inspect.add_argument("--project-mount-root", type=Path, required=True)
    inspect.add_argument("--asset-volume", required=True)
    inspect.add_argument("--project-volume", required=True)
    evaluate_cmd = commands.add_parser("evaluate")
    evaluate_cmd.add_argument("--evidence", type=Path, required=True)
    evaluate_cmd.add_argument("--snapshot", type=Path, required=True)
    evaluate_cmd.add_argument("--allow-isolated-lab", action="store_true")
    evaluate_cmd.add_argument("--max-age-seconds", type=int, default=3600)
    return value


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "inspect-runtime":
            result = inspect_runtime(args)
        else:
            if args.max_age_seconds < 1:
                raise AdmissionError("--max-age-seconds must be positive")
            result = evaluate(
                _json_object(args.evidence),
                _json_object(args.snapshot),
                args.allow_isolated_lab,
                args.max_age_seconds,
            )
    except AdmissionBlocked as exc:
        result = {
            "schema_version": 1,
            "subpart": "FR-06B3A",
            "decision": "blocked",
            "preflight_passed": False,
            "production_authorized": False,
            "executor_present": False,
            "blockers": [str(exc)],
        }
        print(json.dumps(result, sort_keys=True))
        return 2
    except (AdmissionError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"FR06B3A_ADMISSION_ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    if args.command == "evaluate" and not result["preflight_passed"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
