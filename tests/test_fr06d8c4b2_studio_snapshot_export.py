"""Acceptance for the host-side Studio drain snapshot collector."""
from __future__ import annotations

import importlib.util
import json
import stat
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/security/fr06d8c4_studio_snapshot_export.py"
_spec = importlib.util.spec_from_file_location("fr06d8c4_snapshot_export", SCRIPT)
assert _spec is not None and _spec.loader is not None
collector = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(collector)

OPERATION = "11111111-1111-4111-8111-111111111111"


def _payload():
    return {
        "schema": collector.SCHEMA,
        "admission": {
            "schema_version": 7,
            "scope": "project_execution+backup_cycles+academy_course_packages+notification_delivery_dispatch+security_remediation_preparation+security_scan_requests+studio_job_requests",
            "generation": 14,
            "status": "closed",
            "enabled": False,
            "operation_id": OPERATION,
            "reason": "isolated export",
            "changed_at": "2026-09-20T00:00:00+00:00",
            "full_host_closure": False,
        },
        "studio": {
            "scope": "studio_execution_threads",
            "observed_at": "2026-09-20T00:00:30+00:00",
            "executions": [],
            "postcrash_observations": [],
            "admission_closed": True,
            "coverage_unverified": True,
            "full_host_closure": False,
        },
        "backup": {
            "scope": "backup_cycles",
            "observed_at": "2026-09-20T00:01:00+00:00",
            "operation_id": OPERATION,
            "generation": 14,
            "active_count": 0,
            "unresolved_count": 0,
            "expired_count": 0,
            "unfinished_count": 0,
            "coverage_unverified": True,
            "full_host_closure": False,
        },
    }


def test_validate_accepts_exact_bundle_and_rejects_authority_drift():
    payload = _payload()
    assert collector._validate(payload, OPERATION, 14) is payload
    payload["backup"]["generation"] = 15
    with pytest.raises(collector.SnapshotExportBlocked):
        collector._validate(payload, OPERATION, 14)


def test_private_writer_is_create_only_and_mode_0600(tmp_path):
    path = tmp_path / "admission.json"
    collector._write_private(path, {"a": 1})
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads(path.read_text()) == {"a": 1}
    with pytest.raises(collector.SnapshotExportBlocked, match="already exists"):
        collector._write_private(path, {"a": 2})
    assert json.loads(path.read_text()) == {"a": 1}


def test_backend_container_requires_exactly_one(monkeypatch):
    monkeypatch.setattr(collector, "_run", lambda *_args, **_kwargs: "one\ntwo")
    with pytest.raises(collector.SnapshotExportBlocked, match="exactly one"):
        collector._backend_container()


def test_cli_writes_all_three_private_files(tmp_path, monkeypatch):
    payload = _payload()
    monkeypatch.setattr(collector, "_backend_container", lambda: "backend-id")
    monkeypatch.setattr(collector, "_run", lambda *_args, **_kwargs: json.dumps(payload))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT),
            "--operation-id", OPERATION,
            "--generation", "14",
            "--output-dir", str(tmp_path),
        ],
    )
    assert collector.main() == 0
    for name, key in (
        ("admission.json", "admission"),
        ("studio.json", "studio"),
        ("backup.json", "backup"),
    ):
        path = tmp_path / name
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert json.loads(path.read_text()) == payload[key]
    assert collector.main() == 2
