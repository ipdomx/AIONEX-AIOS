from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts" / "recovery" / "fr24_restore_plan.py"
FIXTURE = ROOT / "tests" / "fixtures" / "fr24" / "recovery_manifest.json"

spec = importlib.util.spec_from_file_location("fr24_restore_plan", SOURCE)
assert spec and spec.loader
fr24 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fr24)


def load_fixture() -> dict:
    return json.loads(FIXTURE.read_text())


def test_valid_synthetic_manifest_reports_restore_contract_and_blocked_live_gates():
    report = fr24.validate_recovery_manifest(load_fixture())
    assert report["contract_valid"] is True
    assert report["backup_schema_version"] == 2
    assert report["encrypted_archive_contract"] == {
        "algorithm": "AES-256-GCM",
        "envelope_version": 1,
        "roles": ["database", "platform_asset_snapshot", "manifest"],
    }
    assert report["durable_asset_root_count"] == 11
    assert report["redis_strategy"] == "empty_rebuild"
    assert report["rpo_seconds"] == 600
    assert report["rto_seconds"] == 1800
    assert report["synthetic_measurement"] is True
    assert report["live_recovery_ready"] is False
    assert report["external_gate_blockers"] == [
        "FR-06", "FR-22", "coordinator", "key_custody"
    ]
    assert [step["step"] for step in report["restore_plan"]] == list(range(1, 9))


def test_cli_require_live_ready_fails_closed_without_touching_live_state():
    result = subprocess.run(
        [sys.executable, str(SOURCE), "--manifest", str(FIXTURE), "--require-live-ready"],
        check=False, text=True, capture_output=True,
    )
    assert result.returncode == 3
    report = json.loads(result.stdout)
    assert report["contract_valid"] is True
    assert report["live_recovery_ready"] is False


def test_all_eleven_durable_roots_are_required_exactly_once():
    manifest = load_fixture()
    del manifest["backup"]["platform_asset_snapshot"]["roots"]["security_remediation_data"]
    with pytest.raises(fr24.RecoveryContractError, match="all 11 durable asset roots"):
        fr24.validate_recovery_manifest(manifest)


def test_asset_root_aggregate_counts_must_match_snapshot_totals():
    manifest = load_fixture()
    manifest["backup"]["platform_asset_snapshot"]["roots"]["portal_asset_data"]["file_count"] = 2
    with pytest.raises(fr24.RecoveryContractError, match="file counts"):
        fr24.validate_recovery_manifest(manifest)


def test_manifest_plaintext_digest_binds_backup_inventory():
    manifest = load_fixture()
    manifest["backup"]["database"]["sha256"] = "f" * 64
    with pytest.raises(fr24.RecoveryContractError, match="manifest plaintext SHA-256"):
        fr24.validate_recovery_manifest(manifest)


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("algorithm", "AES-128-GCM", "algorithm"),
        ("envelope_version", 2, "envelope_version"),
        ("ciphertext_size_bytes", 4096, "authenticated-envelope overhead"),
    ],
)
def test_database_encrypted_archive_metadata_fails_closed(field, value, match):
    manifest = load_fixture()
    manifest["backup"]["database"]["encryption"][field] = value
    with pytest.raises(fr24.RecoveryContractError, match=match):
        fr24.validate_recovery_manifest(manifest)


def test_rollback_evidence_must_match_release_and_remain_immutable():
    manifest = load_fixture()
    manifest["rollback"]["overwrite_allowed"] = True
    with pytest.raises(fr24.RecoveryContractError, match="must not be overwrite-authorized"):
        fr24.validate_recovery_manifest(manifest)

    manifest = load_fixture()
    manifest["rollback"]["sourceCommit"] = "b" * 40
    with pytest.raises(fr24.RecoveryContractError, match="rollback.sourceCommit"):
        fr24.validate_recovery_manifest(manifest)


def test_release_runtime_image_count_and_digest_identity_are_consistent():
    manifest = load_fixture()
    manifest["release"]["runtime"]["containerCount"] = 3
    with pytest.raises(fr24.RecoveryContractError, match="containerCount"):
        fr24.validate_recovery_manifest(manifest)


def test_redis_is_rebuilt_empty_not_restored_as_cross_environment_authority():
    manifest = load_fixture()
    manifest["redis"]["recovery_authority"] = True
    with pytest.raises(fr24.RecoveryContractError, match="cross-environment recovery authority"):
        fr24.validate_recovery_manifest(manifest)


def test_synthetic_rpo_rto_requires_monotonic_whole_second_timestamps():
    manifest = load_fixture()
    manifest["synthetic_timeline"]["service_restored_at"] = "2026-10-03T12:14:59+00:00"
    with pytest.raises(fr24.RecoveryContractError, match="must be monotonic"):
        fr24.validate_recovery_manifest(manifest)


def test_live_ready_requires_every_dependency_and_both_external_approvals():
    manifest = load_fixture()
    for key in manifest["gates"]["dependencies"]:
        manifest["gates"]["dependencies"][key] = True
    for key in manifest["gates"]["approvals"]:
        manifest["gates"]["approvals"][key] = True
    report = fr24.validate_recovery_manifest(manifest)
    assert report["live_recovery_ready"] is True
    assert report["external_gate_blockers"] == []


def test_fixture_contains_no_key_material_or_live_paths():
    raw = FIXTURE.read_text()
    assert "key_b64" not in raw
    assert "/run/operator-secrets" not in raw
    assert "/root/.config/aionex" not in raw
    assert "production" not in raw.lower()
