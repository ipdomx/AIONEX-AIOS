"""FR-06D8C4B2 Studio runtime-drain source acceptance."""
from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WRITER_SCRIPT = ROOT / "scripts/security/fr06d8c4_studio_writer_epoch.py"
DRAIN_SCRIPT = ROOT / "scripts/security/fr06d8c4_studio_runtime_drain.py"

_writer_spec = importlib.util.spec_from_file_location(
    "fr06d8c4_writer_epoch_for_b2", WRITER_SCRIPT
)
assert _writer_spec is not None and _writer_spec.loader is not None
writer = importlib.util.module_from_spec(_writer_spec)
_writer_spec.loader.exec_module(writer)

_drain_spec = importlib.util.spec_from_file_location(
    "fr06d8c4_runtime_drain", DRAIN_SCRIPT
)
assert _drain_spec is not None and _drain_spec.loader is not None
drain = importlib.util.module_from_spec(_drain_spec)
_drain_spec.loader.exec_module(drain)

MERGE = "b" * 40
VOLUME = "/var/lib/docker/volumes/web-dashboard_studio_asset_data/_data"


def _admission():
    return {
        "schema_version": 7,
        "scope": (
            "project_execution+backup_cycles+academy_course_packages+"
            "notification_delivery_dispatch+security_remediation_preparation+"
            "security_scan_requests+studio_job_requests"
        ),
        "generation": 14,
        "status": "closed",
        "enabled": False,
        "operation_id": "11111111-1111-4111-8111-111111111111",
        "reason": "isolated C4B2",
        "changed_at": "2026-09-19T20:00:00+00:00",
        "full_host_closure": False,
    }


def _studio():
    return {
        "scope": "studio_execution_threads",
        "observed_at": "2026-09-19T20:03:00+00:00",
        "executions": [],
        "postcrash_observations": [],
        "admission_closed": True,
        "coverage_unverified": True,
        "full_host_closure": False,
    }


def _container(
    service,
    *,
    identifier=None,
    started="2026-09-19T20:02:00+00:00",
    restart_count=0,
    rw=None,
    source=VOLUME,
):
    mounts = []
    if rw is not None:
        mounts.append(
            {
                "Destination": "/var/lib/aionex/studio-assets",
                "Source": source,
                "RW": rw,
                "Type": "volume",
                "Name": "web-dashboard_studio_asset_data",
            }
        )
    return {
        "Id": identifier or f"{service}-container",
        "RestartCount": restart_count,
        "Config": {
            "Labels": {
                "com.docker.compose.project": "web-dashboard",
                "com.docker.compose.service": service,
            }
        },
        "State": {
            "Running": True,
            "Status": "running",
            "StartedAt": started,
        },
        "Mounts": mounts,
    }


def _containers():
    return [
        _container("backend", rw=True),
        _container("studio-worker", rw=True),
        _container("backup-worker", rw=False),
        _container("communication-worker"),
    ]


def _writer_receipt():
    return writer.evaluate(
        admission=_admission(),
        studio_snapshot=_studio(),
        containers=_containers(),
        merge_sha=MERGE,
    )


def _backup():
    return {
        "scope": "backup_cycles",
        "observed_at": (datetime.now(UTC) + timedelta(seconds=5)).isoformat(),
        "operation_id": _admission()["operation_id"],
        "generation": _admission()["generation"],
        "active_count": 0,
        "unresolved_count": 0,
        "expired_count": 0,
        "unfinished_count": 0,
        "coverage_unverified": True,
        "full_host_closure": False,
    }


def test_valid_runtime_drain_keeps_cleanup_boundary_false():
    receipt = drain.evaluate(
        writer_receipt=_writer_receipt(),
        backup_snapshot=_backup(),
        containers=_containers(),
    )
    assert receipt["application_writer_epoch_verified"] is True
    assert receipt["runtime_container_epoch_stable"] is True
    assert receipt["backup_cycle_drain_verified"] is True
    assert receipt["process_drain_verified"] is False
    assert receipt["host_process_scan_verified"] is False
    assert receipt["cleanup_authorized"] is False
    assert receipt["filesystem_mutation_performed"] is False
    assert receipt["full_host_closure"] is False
    assert len(receipt["receipt_sha256"]) == 64


@pytest.mark.parametrize(
    "field",
    ["active_count", "unresolved_count", "expired_count", "unfinished_count"],
)
def test_any_nonzero_backup_cycle_measurement_blocks(field):
    backup = _backup()
    backup[field] = 1
    with pytest.raises(drain.RuntimeDrainBlocked, match=field):
        drain.evaluate(
            writer_receipt=_writer_receipt(),
            backup_snapshot=backup,
            containers=_containers(),
        )


def test_backup_authority_must_match_writer_operation_and_generation():
    backup = _backup()
    backup["generation"] += 1
    with pytest.raises(drain.RuntimeDrainBlocked, match="authority differs"):
        drain.evaluate(
            writer_receipt=_writer_receipt(),
            backup_snapshot=backup,
            containers=_containers(),
        )


def test_backup_snapshot_must_postdate_writer_receipt():
    writer_receipt = _writer_receipt()
    backup = _backup()
    backup["observed_at"] = writer_receipt["observed_at"]
    with pytest.raises(drain.RuntimeDrainBlocked, match="predates"):
        drain.evaluate(
            writer_receipt=writer_receipt,
            backup_snapshot=backup,
            containers=_containers(),
        )


def test_writer_container_identity_cannot_change_after_epoch_receipt():
    containers = _containers()
    containers[0]["Id"] = "replacement-backend"
    with pytest.raises(drain.RuntimeDrainBlocked, match="container changed"):
        drain.evaluate(
            writer_receipt=_writer_receipt(),
            backup_snapshot=_backup(),
            containers=containers,
        )


def test_writer_restart_count_cannot_change_after_epoch_receipt():
    containers = _containers()
    containers[1]["RestartCount"] = 1
    with pytest.raises(drain.RuntimeDrainBlocked, match="restart count changed"):
        drain.evaluate(
            writer_receipt=_writer_receipt(),
            backup_snapshot=_backup(),
            containers=containers,
        )


def test_one_shot_root_initializer_must_not_be_running():
    containers = _containers() + [_container("backup-asset-root-init", rw=True)]
    with pytest.raises(drain.RuntimeDrainBlocked, match="initializer is running"):
        drain.evaluate(
            writer_receipt=_writer_receipt(),
            backup_snapshot=_backup(),
            containers=containers,
        )


def test_reader_container_identity_cannot_change():
    containers = _containers()
    containers[2]["Id"] = "replacement-backup-worker"
    with pytest.raises(drain.RuntimeDrainBlocked, match="reader container changed"):
        drain.evaluate(
            writer_receipt=_writer_receipt(),
            backup_snapshot=_backup(),
            containers=containers,
        )


def test_unexpected_runtime_mount_is_rejected():
    containers = _containers() + [_container("rogue", rw=True)]
    with pytest.raises(drain.RuntimeDrainBlocked, match="unexpected runtime Studio writer"):
        drain.evaluate(
            writer_receipt=_writer_receipt(),
            backup_snapshot=_backup(),
            containers=containers,
        )


def test_tampered_writer_receipt_is_rejected():
    receipt = _writer_receipt()
    receipt["cleanup_authorized"] = True
    with pytest.raises(drain.RuntimeDrainBlocked, match="not an accepted"):
        drain.evaluate(
            writer_receipt=receipt,
            backup_snapshot=_backup(),
            containers=_containers(),
        )


def test_cli_writes_private_immutable_receipt(tmp_path, monkeypatch):
    writer_path = tmp_path / "writer.json"
    backup_path = tmp_path / "backup.json"
    output = tmp_path / "drain.json"
    writer_path.write_text(json.dumps(_writer_receipt()))
    backup_path.write_text(json.dumps(_backup()))
    monkeypatch.setattr(drain, "_containers", _containers)
    monkeypatch.setattr(
        __import__("sys"),
        "argv",
        [
            str(DRAIN_SCRIPT),
            "--writer-receipt",
            str(writer_path),
            "--backup-snapshot",
            str(backup_path),
            "--output",
            str(output),
        ],
    )
    assert drain.main() == 0
    prior = json.loads(output.read_text())
    assert output.stat().st_mode & 0o777 == 0o600
    assert prior["backup_cycle_drain_verified"] is True
    assert drain.main() == 2
    assert json.loads(output.read_text()) == prior
