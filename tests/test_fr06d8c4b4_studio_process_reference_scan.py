"""FR-06D8C4B4 exact Studio process-reference scan acceptance."""
from __future__ import annotations

import importlib.util
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/security/fr06d8c4_studio_process_reference_scan.py"
B1_SCRIPT = ROOT / "scripts/security/fr06d8c4_studio_writer_epoch.py"

_spec = importlib.util.spec_from_file_location("fr06d8c4_process_scan", SCRIPT)
assert _spec is not None and _spec.loader is not None
scan = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan)

_b1_spec = importlib.util.spec_from_file_location("fr06d8c4_writer_epoch", B1_SCRIPT)
assert _b1_spec is not None and _b1_spec.loader is not None
writer_epoch = importlib.util.module_from_spec(_b1_spec)
_b1_spec.loader.exec_module(writer_epoch)

OPERATION = "11111111-1111-4111-8111-111111111111"


def _digest(value, key):
    body = {name: item for name, item in value.items() if name != key}
    value[key] = scan._sha(body)
    return value


def _writer(volume: Path):
    admission = {
        "schema_version": 20,
        "scope": "studio_job_requests",
        "generation": 20,
        "status": "closed",
        "enabled": False,
        "operation_id": OPERATION,
        "reason": "test closed admission",
        "changed_at": "2026-09-20T00:58:00+00:00",
        "full_host_closure": False,
    }
    studio_snapshot = {
        "scope": "studio_execution_threads",
        "observed_at": "2026-09-20T00:59:45+00:00",
        "admission_closed": True,
        "coverage_unverified": True,
        "full_host_closure": False,
        "executions": [],
        "postcrash_observations": [],
    }
    return writer_epoch.evaluate(
        admission=admission,
        studio_snapshot=studio_snapshot,
        containers=_containers(volume),
        merge_sha="a" * 40,
    )


def _runtime(writer):
    return _digest({
        "schema": scan.RUNTIME_SCHEMA,
        "observed_at": (
            datetime.fromisoformat(writer["observed_at"]) + timedelta(seconds=1)
        ).isoformat(),
        "writer_receipt_sha256": writer["receipt_sha256"],
        "merge_sha": writer["merge_sha"],
        "operation_id": writer["admission"]["operation_id"],
        "generation": writer["admission"]["generation"],
        "studio_volume_source": writer["studio_volume_source"],
        "writer_container_ids": sorted(
            row["container_id"] for row in writer["writers"]
        ),
        "backup_snapshot_sha256": "2" * 64,
        "application_writer_epoch_verified": True,
        "runtime_container_epoch_stable": True,
        "backup_cycle_drain_verified": True,
        "process_drain_verified": False,
        "host_process_scan_verified": False,
        "cleanup_authorized": False,
        "filesystem_mutation_performed": False,
        "full_host_closure": False,
    }, "receipt_sha256")


def _identity(path: Path):
    raw = path.stat()
    return {
        "device": raw.st_dev,
        "inode": raw.st_ino,
        "kind": "file",
        "uid": raw.st_uid,
        "gid": raw.st_gid,
        "mode": raw.st_mode & 0o7777,
        "links": raw.st_nlink,
        "size": raw.st_size,
    }


def _candidate(staging: Path, *, layout="owned_staging_present"):
    final = staging.parent / "archive.zip"
    if layout == "owned_staging_and_final_hardlinks":
        os.link(staging, final)
    candidate = {
        "schema": scan.CANDIDATE_SCHEMA,
        "observation_id": "22222222-2222-4222-8222-222222222222",
        "observation_proof_sha256": "3" * 64,
        "execution_id": "33333333-3333-4333-8333-333333333333",
        "publication_id": "44444444-4444-4444-8444-444444444444",
        "job_id": "55555555-5555-4555-8555-555555555555",
        "organization_id": "org",
        "maintenance_operation_id": OPERATION,
        "maintenance_generation": 20,
        "layout": layout,
        "publication_phase": "published" if final.exists() else "staged",
        "publication_evidence_sha256": "4" * 64,
        "relative_components": ["org", "asset", "revision-1"],
        "staging_name": staging.name,
        "final_name": final.name,
        "staging": {"status": "owned", "identity": _identity(staging)},
        "final": (
            {"status": "owned", "identity": _identity(final)}
            if final.exists()
            else {"status": "absent", "identity": None}
        ),
        "action": "remove_owned_staging",
        "process_reference_scan_required": True,
        "final_deletion_permitted": False,
        "cleanup_authorized": False,
        "filesystem_mutation_performed": False,
        "full_host_closure": False,
    }
    return _digest(candidate, "candidate_sha256")


def _container(service, identifier, *, rw=None, started=None):
    mounts = []
    if rw is not None:
        mounts.append({
            "Destination": scan.DESTINATION,
            "Source": None,
            "RW": rw,
            "Type": "volume",
            "Name": "studio-volume",
        })
    starts = {
        "backend": "2026-09-20T00:59:00+00:00",
        "studio-worker": "2026-09-20T00:59:30+00:00",
        "backup-worker": "2026-09-20T00:58:00+00:00",
    }
    return {
        "Id": identifier,
        "RestartCount": 0,
        "Config": {
            "Labels": {
                "com.docker.compose.project": scan.PROJECT,
                "com.docker.compose.service": service,
            }
        },
        "State": {
            "Running": True,
            "Status": "running",
            "StartedAt": started or starts.get(
                service, "2026-09-20T00:57:00+00:00"
            ),
        },
        "Mounts": mounts,
    }


def _containers(volume: Path):
    rows = [
        _container("backend", "backend-id", rw=True),
        _container("studio-worker", "studio-id", rw=True),
        _container("backup-worker", "backup-id", rw=False),
        _container("communication-worker", "comm-id"),
    ]
    for row in rows:
        for mount in row["Mounts"]:
            mount["Source"] = str(volume)
    return rows


def _case(tmp_path: Path, *, layout="owned_staging_present"):
    volume = tmp_path / "volume"
    directory = volume / "org" / "asset" / "revision-1"
    directory.mkdir(parents=True)
    staging = directory / (".studio-publish-" + "0" * 32 + ".partial")
    staging.write_bytes(b"owned staging bytes")
    candidate = _candidate(staging, layout=layout)
    proc = tmp_path / "proc"
    (proc / "100" / "task" / "100" / "fd").mkdir(parents=True)
    (proc / "100" / "map_files").mkdir(parents=True)
    writer = _writer(volume)
    runtime = _runtime(writer)
    return volume, staging, candidate, proc, writer, runtime


def _evaluate(case, *, containers=None, boot_id="boot-123"):
    volume, _staging, candidate, proc, writer, runtime = case
    return scan.evaluate(
        writer_receipt=writer,
        runtime_receipt=runtime,
        cleanup_candidate=candidate,
        containers=containers or _containers(volume),
        proc_root=proc,
        boot_id=boot_id,
    )


@pytest.mark.parametrize(
    "layout",
    ["owned_staging_present", "owned_staging_and_final_hardlinks"],
)
def test_zero_visible_references_proves_only_candidate_reference_drain(
    tmp_path, layout
):
    case = _case(tmp_path, layout=layout)
    _volume, staging, _candidate_row, _proc, _writer_row, _runtime_row = case
    receipt = _evaluate(case)
    assert receipt["candidate_reference_drain_verified"] is True
    assert receipt["host_process_scan_verified"] is True
    assert receipt["scan_passes"] == 2
    assert receipt["visible_reference_count"] == 0
    assert receipt["staging_identity"]["inode"] == staging.stat().st_ino
    assert receipt["process_drain_verified"] is False
    assert receipt["cleanup_authorized"] is False
    assert receipt["filesystem_mutation_performed"] is False
    assert receipt["final_deletion_permitted"] is False
    assert receipt["full_host_closure"] is False
    assert receipt["boot_id"] == "boot-123"


@pytest.mark.parametrize(
    ("relative", "kind"),
    [
        ("100/task/100/fd/7", "fd"),
        ("100/task/100/cwd", "cwd"),
        ("100/task/100/root", "root"),
        ("100/task/100/exe", "exe"),
        ("100/map_files/aaa-bbb", "mmap"),
    ],
)
def test_any_thread_visible_reference_blocks_both_scan_contract(
    tmp_path, relative, kind
):
    case = _case(tmp_path)
    _volume, staging, _candidate_row, proc, _writer_row, _runtime_row = case
    link = proc / relative
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(staging)
    found = scan.scan_proc_references(
        proc_root=proc,
        device=staging.stat().st_dev,
        inode=staging.stat().st_ino,
    )
    assert any(item["kind"] == kind for item in found)
    with pytest.raises(scan.ProcessScanBlocked, match="still has process references"):
        _evaluate(case)


def test_staging_identity_drift_is_fail_closed(tmp_path):
    case = _case(tmp_path)
    _volume, staging, _candidate_row, _proc, _writer_row, _runtime_row = case
    staging.unlink()
    staging.write_bytes(b"replacement")
    with pytest.raises(scan.ProcessScanBlocked, match="staging identity changed"):
        _evaluate(case)


def test_final_appearance_after_staging_only_candidate_is_rejected(tmp_path):
    case = _case(tmp_path)
    _volume, staging, _candidate_row, _proc, _writer_row, _runtime_row = case
    (staging.parent / "archive.zip").write_bytes(b"unexpected")
    with pytest.raises(scan.ProcessScanBlocked, match="final entry changed"):
        _evaluate(case)


def test_runtime_and_candidate_authority_must_match(tmp_path):
    case = _case(tmp_path)
    _volume, _staging, candidate, _proc, _writer_row, _runtime_row = case
    candidate["maintenance_generation"] = 21
    _digest(candidate, "candidate_sha256")
    with pytest.raises(scan.ProcessScanBlocked, match="not scan-eligible"):
        _evaluate(case)


def test_nonstaging_candidate_is_not_scan_eligible(tmp_path):
    case = _case(tmp_path)
    _volume, _staging, candidate, _proc, _writer_row, _runtime_row = case
    candidate["action"] = "no_staging_mutation_required"
    candidate["process_reference_scan_required"] = False
    _digest(candidate, "candidate_sha256")
    with pytest.raises(scan.ProcessScanBlocked, match="not scan-eligible"):
        _evaluate(case)


def test_tampered_runtime_receipt_is_rejected(tmp_path):
    case = _case(tmp_path)
    _volume, _staging, _candidate_row, _proc, _writer_row, runtime = case
    runtime["cleanup_authorized"] = True
    with pytest.raises(scan.ProcessScanBlocked, match="digest differs"):
        _evaluate(case)


def test_changed_writer_epoch_is_rejected(tmp_path):
    case = _case(tmp_path)
    volume = case[0]
    containers = _containers(volume)
    containers[0]["Id"] = "replacement-backend"
    with pytest.raises(scan.ProcessScanBlocked, match="writer epoch changed"):
        _evaluate(case, containers=containers)


def test_real_b1_reader_shape_without_epoch_fields_is_accepted(tmp_path):
    case = _case(tmp_path)
    reader = case[4]["readers"][0]
    assert set(reader) == {
        "service", "container_id", "rw", "source", "type", "name"
    }
    receipt = _evaluate(case)
    assert receipt["host_process_scan_verified"] is True


def test_changed_reader_identity_is_rejected(tmp_path):
    case = _case(tmp_path)
    volume = case[0]
    containers = _containers(volume)
    containers[2]["Id"] = "replacement-backup"
    with pytest.raises(scan.ProcessScanBlocked, match="reader identity changed"):
        _evaluate(case, containers=containers)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("Source", "replacement-source"),
        ("Type", "bind"),
        ("Name", "replacement-volume"),
        ("RW", True),
    ],
)
def test_changed_reader_mount_is_rejected(tmp_path, field, value):
    case = _case(tmp_path)
    volume = case[0]
    containers = _containers(volume)
    if field == "Source":
        value = str(volume / value)
    containers[2]["Mounts"][0][field] = value
    with pytest.raises(scan.ProcessScanBlocked, match="reader mount changed"):
        _evaluate(case, containers=containers)


def test_unexpected_current_writer_is_rejected(tmp_path):
    case = _case(tmp_path)
    volume = case[0]
    containers = _containers(volume)
    rogue = _container("rogue-writer", "rogue-id", rw=True)
    rogue["Mounts"][0]["Source"] = str(volume)
    containers.append(rogue)
    with pytest.raises(scan.ProcessScanBlocked, match="unexpected current Studio writer"):
        _evaluate(case, containers=containers)


def test_running_initializer_is_rejected(tmp_path):
    case = _case(tmp_path)
    volume = case[0]
    containers = _containers(volume)
    init = _container(scan.ONE_SHOT, "init-id", rw=True)
    init["Mounts"][0]["Source"] = str(volume)
    containers.append(init)
    with pytest.raises(scan.ProcessScanBlocked, match="initializer is running"):
        _evaluate(case, containers=containers)


def test_target_change_between_scans_is_rejected(tmp_path, monkeypatch):
    case = _case(tmp_path)
    _volume, staging, _candidate_row, _proc, _writer_row, _runtime_row = case
    calls = 0
    original = scan.scan_proc_references

    def mutate_after_first(**kwargs):
        nonlocal calls
        calls += 1
        result = original(**kwargs)
        if calls == 1:
            staging.unlink()
            staging.write_bytes(b"replacement")
        return result

    monkeypatch.setattr(scan, "scan_proc_references", mutate_after_first)
    with pytest.raises(scan.ProcessScanBlocked, match="identity changed"):
        _evaluate(case)
    assert calls == 1


def test_blank_boot_id_is_rejected(tmp_path):
    case = _case(tmp_path)
    with pytest.raises(scan.ProcessScanBlocked, match="boot id"):
        _evaluate(case, boot_id="   ")


def test_cli_writes_private_immutable_receipt(tmp_path, monkeypatch):
    case = _case(tmp_path)
    volume, _staging, candidate, proc, writer, runtime = case
    writer_path = tmp_path / "writer.json"
    runtime_path = tmp_path / "runtime.json"
    candidate_path = tmp_path / "candidate.json"
    output = tmp_path / "scan.json"
    writer_path.write_text(json.dumps(writer))
    runtime_path.write_text(json.dumps(runtime))
    candidate_path.write_text(json.dumps(candidate))
    monkeypatch.setattr(scan, "_containers", lambda: _containers(volume))
    monkeypatch.setattr(scan, "_boot_id", lambda: "boot-123")
    monkeypatch.setattr(
        __import__("sys"),
        "argv",
        [
            str(SCRIPT),
            "--writer-receipt",
            str(writer_path),
            "--runtime-receipt",
            str(runtime_path),
            "--cleanup-candidate",
            str(candidate_path),
            "--proc-root",
            str(proc),
            "--output",
            str(output),
        ],
    )
    assert scan.main() == 0
    prior = json.loads(output.read_text())
    assert output.stat().st_mode & 0o777 == 0o600
    assert prior["candidate_reference_drain_verified"] is True
    assert prior["scan_passes"] == 2
    assert scan.main() == 2
    assert json.loads(output.read_text()) == prior
