"""FR-06D8C4B Studio writer-epoch source acceptance."""
from __future__ import annotations

import importlib.util
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/security/fr06d8c4_studio_writer_epoch.py"

_spec = importlib.util.spec_from_file_location("fr06d8c4_writer_epoch", SCRIPT)
assert _spec is not None and _spec.loader is not None
module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(module)

MERGE = "a" * 40
VOLUME = "/var/lib/docker/volumes/web-dashboard_studio_asset_data/_data"


def _admission():
    return {
        "schema_version": 7,
        "scope": (
            "project_execution+backup_cycles+academy_course_packages+"
            "notification_delivery_dispatch+security_remediation_preparation+"
            "security_scan_requests+studio_job_requests"
        ),
        "generation": 11,
        "status": "closed",
        "enabled": False,
        "operation_id": "11111111-1111-4111-8111-111111111111",
        "reason": "isolated writer epoch",
        "changed_at": "2026-09-19T17:00:00+00:00",
        "full_host_closure": False,
    }


def _studio():
    return {
        "scope": "studio_execution_threads",
        "observed_at": "2026-09-19T17:03:00+00:00",
        "executions": [],
        "postcrash_observations": [
            {
                "observation_id": "22222222-2222-4222-8222-222222222222",
                "requires_reconciliation": True,
                "process_drain_verified": False,
                "cleanup_authorized": False,
            }
        ],
        "admission_closed": True,
        "coverage_unverified": True,
        "full_host_closure": False,
    }


def _container(service, *, started="2026-09-19T17:02:00+00:00", rw=None, source=VOLUME):
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
        "Id": f"{service}-container",
        "RestartCount": 0,
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
        _container("communication-worker", rw=None),
    ]


def test_valid_epoch_proves_only_application_writer_generation():
    receipt = module.evaluate(
        admission=_admission(),
        studio_snapshot=_studio(),
        containers=_containers(),
        merge_sha=MERGE,
    )
    assert receipt["application_writer_epoch_verified"] is True
    assert {row["service"] for row in receipt["writers"]} == {
        "backend",
        "studio-worker",
    }
    assert [row["service"] for row in receipt["readers"]] == ["backup-worker"]
    assert receipt["process_drain_verified"] is False
    assert receipt["host_process_scan_verified"] is False
    assert receipt["backup_cycle_drain_verified"] is False
    assert receipt["cleanup_authorized"] is False
    assert receipt["filesystem_mutation_performed"] is False
    assert receipt["full_host_closure"] is False
    assert len(receipt["receipt_sha256"]) == 64


def test_writer_not_restarted_after_closure_is_rejected():
    containers = _containers()
    containers[0]["State"]["StartedAt"] = "2026-09-19T16:59:59+00:00"
    with pytest.raises(module.DrainBlocked, match="not restarted"):
        module.evaluate(
            admission=_admission(),
            studio_snapshot=_studio(),
            containers=containers,
            merge_sha=MERGE,
        )


def test_unexpected_read_write_writer_is_rejected():
    containers = _containers() + [_container("rogue-writer", rw=True)]
    with pytest.raises(module.DrainBlocked, match="unexpected Studio writer"):
        module.evaluate(
            admission=_admission(),
            studio_snapshot=_studio(),
            containers=containers,
            merge_sha=MERGE,
        )


def test_unknown_reader_is_rejected_until_scope_is_explicit():
    containers = _containers() + [_container("unknown-reader", rw=False)]
    with pytest.raises(module.DrainBlocked, match="unexpected Studio reader"):
        module.evaluate(
            admission=_admission(),
            studio_snapshot=_studio(),
            containers=containers,
            merge_sha=MERGE,
        )


def test_snapshot_must_postdate_all_restarted_writers():
    studio = _studio()
    studio["observed_at"] = "2026-09-19T17:01:59+00:00"
    with pytest.raises(module.DrainBlocked, match="snapshot predates"):
        module.evaluate(
            admission=_admission(),
            studio_snapshot=studio,
            containers=_containers(),
            merge_sha=MERGE,
        )


def test_crash_observation_cannot_be_prematurely_cleared():
    studio = _studio()
    studio["postcrash_observations"][0]["requires_reconciliation"] = False
    with pytest.raises(module.DrainBlocked, match="prematurely cleared"):
        module.evaluate(
            admission=_admission(),
            studio_snapshot=studio,
            containers=_containers(),
            merge_sha=MERGE,
        )


def test_volume_identity_must_be_single_and_shared():
    containers = _containers()
    containers[2]["Mounts"][0]["Source"] = "/other/studio-volume"
    with pytest.raises(module.DrainBlocked, match="volume identity is ambiguous"):
        module.evaluate(
            admission=_admission(),
            studio_snapshot=_studio(),
            containers=containers,
            merge_sha=MERGE,
        )


def test_open_admission_is_rejected():
    admission = _admission()
    admission["status"] = "open"
    admission["enabled"] = True
    with pytest.raises(module.DrainBlocked, match="not a closed Studio authority"):
        module.evaluate(
            admission=admission,
            studio_snapshot=_studio(),
            containers=_containers(),
            merge_sha=MERGE,
        )


def test_missing_writer_container_is_rejected():
    containers = [row for row in _containers() if row["Config"]["Labels"][
        "com.docker.compose.service"
    ] != "backend"]
    with pytest.raises(module.DrainBlocked, match="exactly one running backend"):
        module.evaluate(
            admission=_admission(),
            studio_snapshot=_studio(),
            containers=containers,
            merge_sha=MERGE,
        )


def test_non_project_containers_do_not_affect_writer_inventory():
    containers = _containers()
    other = deepcopy(_container("rogue-writer", rw=True))
    other["Config"]["Labels"]["com.docker.compose.project"] = "other-project"
    containers.append(other)
    receipt = module.evaluate(
        admission=_admission(),
        studio_snapshot=_studio(),
        containers=containers,
        merge_sha=MERGE,
    )
    assert receipt["application_writer_epoch_verified"] is True


def test_cli_writes_one_private_receipt_and_refuses_overwrite(tmp_path, monkeypatch):
    admission_path = tmp_path / "admission.json"
    studio_path = tmp_path / "studio.json"
    output = tmp_path / "receipt.json"
    admission_path.write_text(__import__("json").dumps(_admission()))
    studio_path.write_text(__import__("json").dumps(_studio()))

    monkeypatch.setattr(module, "_git_gate", lambda root, sha: None)
    monkeypatch.setattr(module, "_containers", _containers)
    monkeypatch.setattr(
        __import__("sys"),
        "argv",
        [
            str(SCRIPT),
            "--root",
            str(ROOT),
            "--admission-snapshot",
            str(admission_path),
            "--studio-snapshot",
            str(studio_path),
            "--merge-sha",
            MERGE,
            "--output",
            str(output),
        ],
    )
    assert module.main() == 0
    payload = __import__("json").loads(output.read_text())
    assert payload["application_writer_epoch_verified"] is True
    assert output.stat().st_mode & 0o777 == 0o600

    # A prior receipt is immutable input to the next stage, never overwritten.
    assert module.main() == 2
    assert __import__("json").loads(output.read_text()) == payload
