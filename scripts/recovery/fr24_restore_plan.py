#!/usr/bin/env python3
"""Deterministic FR-24 server-loss recovery-plan contract validator.

This module is deliberately side-effect free: it validates sanitized recovery
metadata and computes a synthetic RPO/RTO report.  It never reads recovery
keys, contacts storage, touches databases, mounts filesystems, starts services,
or performs a restore.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any
from uuid import UUID


BACKUP_SCHEMA_VERSION = 2
RECOVERY_SCHEMA_VERSION = 1
ENVELOPE_ALGORITHM = "AES-256-GCM"
ENVELOPE_VERSION = 1
REQUIRED_ASSET_ROOTS = (
    "three_d_asset_data",
    "project_execution_data",
    "course_package_data",
    "media_asset_data",
    "studio_asset_data",
    "portal_asset_data",
    "mobile_release_data",
    "realtime_recording_data",
    "audio_song_ingress_data",
    "security_source_data",
    "security_remediation_data",
)
_REQUIRED_DEPENDENCIES = ("FR-05", "FR-06", "FR-22")
_REQUIRED_APPROVALS = ("coordinator", "key_custody")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_KEY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")

RESTORE_PLAN = (
    {
        "step": 1,
        "action": "verify_encrypted_backup_inventory",
        "scope": "metadata_only",
    },
    {
        "step": 2,
        "action": "stage_database_to_isolated_scratch",
        "scope": "controlled_drill_only",
    },
    {
        "step": 3,
        "action": "stage_platform_assets_to_isolated_root",
        "scope": "controlled_drill_only",
    },
    {
        "step": 4,
        "action": "reconstruct_application_from_release_evidence",
        "scope": "controlled_drill_only",
    },
    {
        "step": 5,
        "action": "start_redis_empty_and_reconcile",
        "scope": "controlled_drill_only",
    },
    {
        "step": 6,
        "action": "validate_links_files_configuration_and_rollback",
        "scope": "controlled_drill_only",
    },
    {
        "step": 7,
        "action": "measure_rpo_rto",
        "scope": "synthetic_now_real_during_authorized_drill",
    },
    {
        "step": 8,
        "action": "controlled_live_recovery_drill",
        "scope": "external_gates_required",
    },
)


class RecoveryContractError(ValueError):
    """Sanitized recovery metadata violates the FR-24 contract."""


def _fail(message: str) -> None:
    raise RecoveryContractError(message)


def _exact_keys(value: Any, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(f"{label} must be an object")
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        _fail(f"{label} fields mismatch: missing={missing} extra={extra}")
    return value


def _int(value: Any, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        _fail(f"{label} must be an integer >= {minimum}")
    return value


def _sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        _fail(f"{label} must be a lowercase SHA-256 hex digest")
    return value


def _timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        _fail(f"{label} must be a timezone-aware timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RecoveryContractError(f"{label} must be a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail(f"{label} must include a timezone")
    return parsed


def _backup_uuid(value: Any) -> str:
    if not isinstance(value, str):
        _fail("backup.backup_id must be a UUID")
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError) as exc:
        raise RecoveryContractError("backup.backup_id must be a UUID") from exc
    if str(parsed) != value.lower():
        _fail("backup.backup_id must use canonical UUID form")
    return value


def _validate_encrypted_artifact(
    value: Any,
    *,
    label: str,
    backup_id: str,
    filename: str,
    extra_fields: set[str] | None = None,
) -> dict[str, Any]:
    expected = {"key", "sha256", "size_bytes", "encryption"} | (extra_fields or set())
    artifact = _exact_keys(value, expected, label)

    key = artifact["key"]
    if not isinstance(key, str) or not key or "\x00" in key or len(key) > 1024:
        _fail(f"{label}.key is invalid")
    suffix = f"/{backup_id}/{filename}"
    if not key.endswith(suffix):
        _fail(f"{label}.key does not bind to backup_id/expected filename")

    _sha256(artifact["sha256"], f"{label}.sha256")
    plaintext_size = _int(artifact["size_bytes"], f"{label}.size_bytes", minimum=1)

    encryption = _exact_keys(
        artifact["encryption"],
        {
            "algorithm",
            "envelope_version",
            "key_id",
            "ciphertext_sha256",
            "ciphertext_size_bytes",
        },
        f"{label}.encryption",
    )
    if encryption["algorithm"] != ENVELOPE_ALGORITHM:
        _fail(f"{label}.encryption.algorithm must be {ENVELOPE_ALGORITHM}")
    if encryption["envelope_version"] != ENVELOPE_VERSION:
        _fail(f"{label}.encryption.envelope_version must be {ENVELOPE_VERSION}")
    key_id = encryption["key_id"]
    if not isinstance(key_id, str) or _KEY_ID.fullmatch(key_id) is None:
        _fail(f"{label}.encryption.key_id is invalid")
    _sha256(
        encryption["ciphertext_sha256"],
        f"{label}.encryption.ciphertext_sha256",
    )
    ciphertext_size = _int(
        encryption["ciphertext_size_bytes"],
        f"{label}.encryption.ciphertext_size_bytes",
        minimum=1,
    )
    if ciphertext_size <= plaintext_size:
        _fail(f"{label} ciphertext must include authenticated-envelope overhead")
    return artifact


def _manifest_plaintext_payload(backup: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": backup["schema_version"],
        "backup_id": backup["backup_id"],
        "created_at": backup["created_at"],
        "encryption_required": backup["encryption_required"],
        "database": backup["database"],
        "platform_asset_snapshot": backup["platform_asset_snapshot"],
    }


def canonical_backup_manifest_bytes(backup: dict[str, Any]) -> bytes:
    """Return the exact FR-05 schema-2 manifest plaintext serialization."""
    return json.dumps(
        _manifest_plaintext_payload(backup),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _validate_backup(value: Any) -> dict[str, Any]:
    backup = _exact_keys(
        value,
        {
            "schema_version",
            "backup_id",
            "created_at",
            "encryption_required",
            "database",
            "platform_asset_snapshot",
            "manifest",
        },
        "backup",
    )
    if backup["schema_version"] != BACKUP_SCHEMA_VERSION:
        _fail(f"backup.schema_version must be {BACKUP_SCHEMA_VERSION}")
    backup_id = _backup_uuid(backup["backup_id"])
    _timestamp(backup["created_at"], "backup.created_at")
    if backup["encryption_required"] is not True:
        _fail("backup.encryption_required must be true")

    _validate_encrypted_artifact(
        backup["database"],
        label="backup.database",
        backup_id=backup_id,
        filename="database.dump.aex1",
    )
    snapshot = _validate_encrypted_artifact(
        backup["platform_asset_snapshot"],
        label="backup.platform_asset_snapshot",
        backup_id=backup_id,
        filename="platform-assets.tar.aex1",
        extra_fields={"file_count", "payload_bytes", "roots"},
    )
    file_count = _int(
        snapshot["file_count"],
        "backup.platform_asset_snapshot.file_count",
        minimum=1,
    )
    payload_bytes = _int(
        snapshot["payload_bytes"],
        "backup.platform_asset_snapshot.payload_bytes",
        minimum=1,
    )
    roots = snapshot["roots"]
    if not isinstance(roots, dict):
        _fail("backup.platform_asset_snapshot.roots must be an object")
    if set(roots) != set(REQUIRED_ASSET_ROOTS):
        _fail(
            "backup.platform_asset_snapshot.roots must contain all 11 durable "
            "asset roots exactly once"
        )
    counted_files = 0
    counted_bytes = 0
    for root_id in REQUIRED_ASSET_ROOTS:
        stats = _exact_keys(
            roots[root_id],
            {"file_count", "payload_bytes"},
            f"backup.platform_asset_snapshot.roots.{root_id}",
        )
        counted_files += _int(
            stats["file_count"],
            f"backup.platform_asset_snapshot.roots.{root_id}.file_count",
        )
        counted_bytes += _int(
            stats["payload_bytes"],
            f"backup.platform_asset_snapshot.roots.{root_id}.payload_bytes",
        )
    if counted_files != file_count:
        _fail("platform asset root file counts do not equal snapshot file_count")
    if counted_bytes != payload_bytes:
        _fail("platform asset root payload bytes do not equal snapshot payload_bytes")

    manifest = _validate_encrypted_artifact(
        backup["manifest"],
        label="backup.manifest",
        backup_id=backup_id,
        filename="manifest.json.aex1",
    )
    manifest_bytes = canonical_backup_manifest_bytes(backup)
    digest = hashlib.sha256(manifest_bytes).hexdigest()
    if manifest["sha256"] != digest:
        _fail("backup.manifest plaintext SHA-256 does not match schema-2 manifest payload")
    if manifest["size_bytes"] != len(manifest_bytes):
        _fail("backup.manifest plaintext size does not match schema-2 manifest payload")
    return backup


def _validate_release(value: Any) -> dict[str, Any]:
    release = _exact_keys(
        value,
        {
            "schemaVersion",
            "sourceCommit",
            "sourceTreeClean",
            "components",
            "compose",
            "runtime",
        },
        "release",
    )
    if release["schemaVersion"] != 1:
        _fail("release.schemaVersion must be 1")
    source_commit = release["sourceCommit"]
    if not isinstance(source_commit, str) or _GIT_SHA.fullmatch(source_commit) is None:
        _fail("release.sourceCommit must be a 40-character lowercase git SHA")
    if release["sourceTreeClean"] is not True:
        _fail("release.sourceTreeClean must be true")

    components = release["components"]
    if not isinstance(components, dict) or not components:
        _fail("release.components must be a non-empty object")
    for name, version in components.items():
        if not isinstance(name, str) or not name or not isinstance(version, str) or not version:
            _fail("release.components must contain non-empty string names/versions")

    compose = _exact_keys(
        release["compose"],
        {"webDashboardSha256", "deploySha256"},
        "release.compose",
    )
    _sha256(compose["webDashboardSha256"], "release.compose.webDashboardSha256")
    _sha256(compose["deploySha256"], "release.compose.deploySha256")

    runtime = _exact_keys(
        release["runtime"],
        {"alembicHeads", "containerCount", "containerImageIds"},
        "release.runtime",
    )
    heads = runtime["alembicHeads"]
    if (
        not isinstance(heads, list)
        or not heads
        or any(not isinstance(item, str) or not item for item in heads)
        or len(set(heads)) != len(heads)
    ):
        _fail("release.runtime.alembicHeads must be a non-empty unique string list")
    images = runtime["containerImageIds"]
    if not isinstance(images, dict) or not images:
        _fail("release.runtime.containerImageIds must be a non-empty object")
    for name, image_id in images.items():
        if (
            not isinstance(name, str)
            or not name
            or not isinstance(image_id, str)
            or _IMAGE_ID.fullmatch(image_id) is None
        ):
            _fail("release.runtime.containerImageIds contains an invalid image ID")
    if _int(runtime["containerCount"], "release.runtime.containerCount", minimum=1) != len(images):
        _fail("release.runtime.containerCount does not match containerImageIds")
    return release


def _validate_rollback(value: Any, release: dict[str, Any]) -> dict[str, Any]:
    rollback = _exact_keys(
        value,
        {
            "preserved",
            "overwrite_allowed",
            "sourceCommit",
            "compose",
            "containerImageIds",
            "alembicHeads",
        },
        "rollback",
    )
    if rollback["preserved"] is not True:
        _fail("rollback evidence must be preserved")
    if rollback["overwrite_allowed"] is not False:
        _fail("rollback evidence must not be overwrite-authorized")
    if rollback["sourceCommit"] != release["sourceCommit"]:
        _fail("rollback.sourceCommit must match release.sourceCommit")
    if rollback["compose"] != release["compose"]:
        _fail("rollback.compose must match release.compose")
    if rollback["containerImageIds"] != release["runtime"]["containerImageIds"]:
        _fail("rollback.containerImageIds must match release runtime image IDs")
    if rollback["alembicHeads"] != release["runtime"]["alembicHeads"]:
        _fail("rollback.alembicHeads must match release runtime Alembic heads")
    return rollback


def _validate_redis(value: Any) -> None:
    redis = _exact_keys(
        value,
        {"recovery_authority", "strategy"},
        "redis",
    )
    if redis["recovery_authority"] is not False:
        _fail("Redis must not be treated as cross-environment recovery authority")
    if redis["strategy"] != "empty_rebuild":
        _fail("Redis recovery strategy must be empty_rebuild")


def _validate_gates(value: Any) -> tuple[bool, list[str]]:
    gates = _exact_keys(value, {"dependencies", "approvals"}, "gates")
    dependencies = _exact_keys(
        gates["dependencies"],
        set(_REQUIRED_DEPENDENCIES),
        "gates.dependencies",
    )
    approvals = _exact_keys(
        gates["approvals"],
        set(_REQUIRED_APPROVALS),
        "gates.approvals",
    )
    blockers: list[str] = []
    for item in _REQUIRED_DEPENDENCIES:
        state = dependencies[item]
        if not isinstance(state, bool):
            _fail(f"gates.dependencies.{item} must be boolean")
        if not state:
            blockers.append(item)
    for item in _REQUIRED_APPROVALS:
        state = approvals[item]
        if not isinstance(state, bool):
            _fail(f"gates.approvals.{item} must be boolean")
        if not state:
            blockers.append(item)
    return not blockers, blockers


def measure_synthetic_rpo_rto(value: Any) -> dict[str, int]:
    timeline = _exact_keys(
        value,
        {
            "backup_cutoff_at",
            "loss_detected_at",
            "recovery_started_at",
            "service_restored_at",
        },
        "synthetic_timeline",
    )
    backup = _timestamp(timeline["backup_cutoff_at"], "synthetic_timeline.backup_cutoff_at")
    loss = _timestamp(timeline["loss_detected_at"], "synthetic_timeline.loss_detected_at")
    started = _timestamp(
        timeline["recovery_started_at"],
        "synthetic_timeline.recovery_started_at",
    )
    restored = _timestamp(
        timeline["service_restored_at"],
        "synthetic_timeline.service_restored_at",
    )
    if not backup <= loss <= started <= restored:
        _fail("synthetic recovery timestamps must be monotonic")
    rpo = (loss - backup).total_seconds()
    rto = (restored - started).total_seconds()
    if rpo < 0 or rto < 0 or not rpo.is_integer() or not rto.is_integer():
        _fail("synthetic RPO/RTO must resolve to non-negative whole seconds")
    return {"rpo_seconds": int(rpo), "rto_seconds": int(rto)}


def validate_recovery_manifest(value: Any) -> dict[str, Any]:
    manifest = _exact_keys(
        value,
        {
            "schema_version",
            "backup",
            "release",
            "rollback",
            "redis",
            "gates",
            "synthetic_timeline",
        },
        "recovery",
    )
    if manifest["schema_version"] != RECOVERY_SCHEMA_VERSION:
        _fail(f"recovery.schema_version must be {RECOVERY_SCHEMA_VERSION}")

    backup = _validate_backup(manifest["backup"])
    release = _validate_release(manifest["release"])
    _validate_rollback(manifest["rollback"], release)
    _validate_redis(manifest["redis"])
    ready, blockers = _validate_gates(manifest["gates"])
    timing = measure_synthetic_rpo_rto(manifest["synthetic_timeline"])

    return {
        "contract_valid": True,
        "backup_id": backup["backup_id"],
        "backup_schema_version": backup["schema_version"],
        "encrypted_archive_contract": {
            "algorithm": ENVELOPE_ALGORITHM,
            "envelope_version": ENVELOPE_VERSION,
            "roles": ["database", "platform_asset_snapshot", "manifest"],
        },
        "durable_asset_root_count": len(REQUIRED_ASSET_ROOTS),
        "source_commit": release["sourceCommit"],
        "redis_strategy": "empty_rebuild",
        **timing,
        "synthetic_measurement": True,
        "live_recovery_ready": ready,
        "external_gate_blockers": blockers,
        "restore_plan": list(RESTORE_PLAN),
    }


def _load(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate a sanitized FR-24 recovery manifest without recovery effects."
    )
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument(
        "--require-live-ready",
        action="store_true",
        help="Return exit 3 when external FR-24 live-recovery gates remain open.",
    )
    args = parser.parse_args(argv)
    try:
        report = validate_recovery_manifest(_load(args.manifest))
    except (OSError, json.JSONDecodeError, RecoveryContractError) as exc:
        print(f"FR24_RECOVERY_CONTRACT_INVALID: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    if args.require_live_ready and not report["live_recovery_ready"]:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
