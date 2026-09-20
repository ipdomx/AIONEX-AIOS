"""FR-06D8C4B5 retained Studio staging quarantine acceptance."""
from __future__ import annotations

import importlib.util
import json
import os
import stat
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/security/fr06d8c4_studio_staging_quarantine.py"
B1_SCRIPT = ROOT / "scripts/security/fr06d8c4_studio_writer_epoch.py"

_spec = importlib.util.spec_from_file_location("fr06d8c4_b5", SCRIPT)
assert _spec is not None and _spec.loader is not None
b5 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(b5)

_b1_spec = importlib.util.spec_from_file_location("fr06d8c4_b1_for_b5", B1_SCRIPT)
assert _b1_spec is not None and _b1_spec.loader is not None
writer_epoch = importlib.util.module_from_spec(_b1_spec)
_b1_spec.loader.exec_module(writer_epoch)

OPERATION = "11111111-1111-4111-8111-111111111111"


def _digest(value, key):
    body = {name: item for name, item in value.items() if name != key}
    value[key] = b5._sha(body)
    return value


def _identity(path: Path):
    raw = path.stat()
    return {
        "device": raw.st_dev,
        "inode": raw.st_ino,
        "kind": "file" if stat.S_ISREG(raw.st_mode) else "other",
        "uid": raw.st_uid,
        "gid": raw.st_gid,
        "mode": stat.S_IMODE(raw.st_mode),
        "links": raw.st_nlink,
        "size": raw.st_size,
    }


def _container(service, identifier, *, rw=None, started=None):
    mounts = []
    if rw is not None:
        mounts.append({
            "Destination": b5.scan.DESTINATION,
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
                "com.docker.compose.project": b5.scan.PROJECT,
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
    receipt = writer_epoch.evaluate(
        admission=admission,
        studio_snapshot=studio_snapshot,
        containers=_containers(volume),
        merge_sha="a" * 40,
    )
    # Keep the real B1 schema/evidence shape while pinning only the observation
    # clock to a deterministic past instant for strict B1 < B2 < B4 ordering.
    receipt["observed_at"] = "2026-09-20T01:00:00+00:00"
    return _digest(receipt, "receipt_sha256")


def _runtime(writer):
    return _digest({
        "schema": b5.scan.RUNTIME_SCHEMA,
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


def _candidate(staging: Path, *, layout="owned_staging_present"):
    final = staging.parent / "archive.zip"
    if layout == "owned_staging_and_final_hardlinks":
        os.link(staging, final)
    value = {
        "schema": b5.scan.CANDIDATE_SCHEMA,
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
    return _digest(value, "candidate_sha256")


def _proc_root(tmp_path: Path):
    proc = tmp_path / "proc"
    (proc / "100" / "task" / "100" / "fd").mkdir(parents=True)
    (proc / "100" / "map_files").mkdir(parents=True)
    return proc


def _case(tmp_path: Path, *, layout="owned_staging_present"):
    volume = tmp_path / "volume"
    directory = volume / "org" / "asset" / "revision-1"
    directory.mkdir(parents=True)
    staging = directory / (".studio-publish-" + "0" * 32 + ".partial")
    staging.write_bytes(b"owned staging bytes")
    candidate = _candidate(staging, layout=layout)
    proc = _proc_root(tmp_path)
    writer = _writer(volume)
    runtime = _runtime(writer)
    containers = _containers(volume)
    prior = b5.scan.evaluate(
        writer_receipt=writer,
        runtime_receipt=runtime,
        cleanup_candidate=candidate,
        containers=containers,
        proc_root=proc,
        boot_id="boot-123",
    )
    return volume, staging, candidate, proc, writer, runtime, containers, prior


def _evaluate(case, *, containers=None, boot_id="boot-123"):
    volume, _staging, candidate, proc, writer, runtime, current, prior = case
    return b5.evaluate_and_quarantine(
        writer_receipt=writer,
        runtime_receipt=runtime,
        cleanup_candidate=candidate,
        process_scan_receipt=prior,
        container_provider=lambda: containers or current,
        proc_root=proc,
        boot_id=boot_id,
    )


@pytest.mark.parametrize(
    "layout",
    ["owned_staging_present", "owned_staging_and_final_hardlinks"],
)
def test_quarantine_retains_inode_and_never_deletes_final(tmp_path, layout):
    case = _case(tmp_path, layout=layout)
    _volume, staging, candidate, _proc, _writer, _runtime, _containers_row, _prior = case
    before = _identity(staging)
    final = staging.parent / candidate["final_name"]

    receipt = _evaluate(case)

    quarantine = staging.parent / receipt["quarantine_name"]
    assert not staging.exists()
    assert quarantine.read_bytes() == b"owned staging bytes"
    assert _identity(quarantine) == before
    if layout == "owned_staging_and_final_hardlinks":
        assert final.exists()
        assert final.stat().st_ino == quarantine.stat().st_ino
        assert final.read_bytes() == b"owned staging bytes"
    else:
        assert not final.exists()
    assert receipt["staging_namespace_detached"] is True
    assert receipt["quarantine_inode_retained"] is True
    assert receipt["final_layout_preserved"] is True
    assert receipt["pre_quarantine_scan_passes"] == 2
    assert receipt["post_quarantine_scan_passes"] == 2
    assert receipt["mutation_performed_by_this_run"] is True
    assert receipt["recovered_existing_quarantine"] is False
    assert receipt["filesystem_mutation_performed"] is True
    assert receipt["process_drain_verified"] is False
    assert receipt["cleanup_authorized"] is False
    assert receipt["settlement_authorized"] is False
    assert receipt["quarantine_deletion_permitted"] is False
    assert receipt["final_deletion_permitted"] is False
    assert receipt["full_host_closure"] is False


def test_quarantine_name_is_deterministic_and_candidate_bound(tmp_path):
    case = _case(tmp_path)
    candidate = case[2]
    expected = f".studio-quarantine-{candidate['candidate_sha256']}.retained"
    assert b5._quarantine_name(candidate["candidate_sha256"]) == expected
    receipt = _evaluate(case)
    assert receipt["quarantine_name"] == expected


def test_foreign_existing_quarantine_blocks_without_mutation(tmp_path):
    case = _case(tmp_path)
    staging, candidate = case[1], case[2]
    quarantine = staging.parent / b5._quarantine_name(candidate["candidate_sha256"])
    quarantine.write_bytes(b"foreign")
    with pytest.raises(b5.StagingQuarantineBlocked, match="both exist"):
        _evaluate(case)
    assert staging.read_bytes() == b"owned staging bytes"
    assert quarantine.read_bytes() == b"foreign"


def test_visible_reference_blocks_before_rename(tmp_path):
    case = _case(tmp_path)
    staging, proc = case[1], case[3]
    link = proc / "100" / "task" / "100" / "fd" / "7"
    link.symlink_to(staging)
    with pytest.raises(b5.StagingQuarantineBlocked, match="visible references"):
        _evaluate(case)
    assert staging.exists()


def test_tampered_process_scan_receipt_blocks_without_mutation(tmp_path):
    case = _case(tmp_path)
    staging, prior = case[1], case[7]
    prior["candidate_reference_drain_verified"] = False
    with pytest.raises(b5.StagingQuarantineBlocked, match="digest differs"):
        _evaluate(case)
    assert staging.exists()


def test_process_scan_boot_binding_is_required(tmp_path):
    case = _case(tmp_path)
    staging = case[1]
    with pytest.raises(b5.StagingQuarantineBlocked, match="boundary is invalid"):
        _evaluate(case, boot_id="other-boot")
    assert staging.exists()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("Source", "replacement-source"),
        ("Type", "bind"),
        ("Name", "replacement-volume"),
        ("RW", True),
    ],
)
def test_current_reader_mount_drift_blocks_without_mutation(
    tmp_path, field, value
):
    case = _case(tmp_path)
    volume, staging = case[0], case[1]
    containers = _containers(volume)
    if field == "Source":
        value = str(volume / value)
    containers[2]["Mounts"][0][field] = value
    with pytest.raises(b5.StagingQuarantineBlocked):
        _evaluate(case, containers=containers)
    assert staging.exists()


def test_fresh_container_inventory_drift_before_rename_blocks_mutation(
    tmp_path
):
    case = _case(tmp_path)
    volume, staging, candidate, proc, writer, runtime, _current, prior = case
    quarantine = staging.parent / b5._quarantine_name(candidate["candidate_sha256"])
    calls = 0

    def provider():
        nonlocal calls
        calls += 1
        rows = _containers(volume)
        if calls >= 2:
            rows[0]["Id"] = "replacement-backend"
        return rows

    with pytest.raises(b5.StagingQuarantineBlocked, match="writer epoch changed"):
        b5.evaluate_and_quarantine(
            writer_receipt=writer,
            runtime_receipt=runtime,
            cleanup_candidate=candidate,
            process_scan_receipt=prior,
            container_provider=provider,
            proc_root=proc,
            boot_id="boot-123",
        )

    assert calls == 2
    assert staging.exists()
    assert not quarantine.exists()


def test_success_reads_four_fresh_container_inventories(tmp_path):
    case = _case(tmp_path)
    volume, _staging, _candidate_row, proc, writer, runtime, _current, prior = case
    calls = 0

    def provider():
        nonlocal calls
        calls += 1
        return _containers(volume)

    receipt = b5.evaluate_and_quarantine(
        writer_receipt=writer,
        runtime_receipt=runtime,
        cleanup_candidate=case[2],
        process_scan_receipt=prior,
        container_provider=provider,
        proc_root=proc,
        boot_id="boot-123",
    )
    assert calls == 4
    assert receipt["staging_namespace_detached"] is True


def test_fresh_container_inventory_drift_after_rename_blocks_receipt(
    tmp_path
):
    case = _case(tmp_path)
    volume, staging, candidate, proc, writer, runtime, _current, prior = case
    quarantine = staging.parent / b5._quarantine_name(candidate["candidate_sha256"])
    calls = 0

    def provider():
        nonlocal calls
        calls += 1
        rows = _containers(volume)
        if calls >= 3:
            rows[0]["Id"] = "replacement-backend"
        return rows

    with pytest.raises(b5.StagingQuarantineBlocked, match="writer epoch changed"):
        b5.evaluate_and_quarantine(
            writer_receipt=writer,
            runtime_receipt=runtime,
            cleanup_candidate=candidate,
            process_scan_receipt=prior,
            container_provider=provider,
            proc_root=proc,
            boot_id="boot-123",
        )

    assert calls == 3
    assert not staging.exists()
    assert quarantine.exists()


def test_container_inventory_provider_failure_is_fail_closed(tmp_path):
    case = _case(tmp_path)
    _volume, staging, candidate, proc, writer, runtime, _current, prior = case

    def provider():
        raise RuntimeError("inventory unavailable")

    with pytest.raises(
        b5.StagingQuarantineBlocked,
        match="current container inventory is unavailable",
    ):
        b5.evaluate_and_quarantine(
            writer_receipt=writer,
            runtime_receipt=runtime,
            cleanup_candidate=candidate,
            process_scan_receipt=prior,
            container_provider=provider,
            proc_root=proc,
            boot_id="boot-123",
        )
    assert staging.exists()


def test_malformed_container_inventory_is_fail_closed(tmp_path):
    case = _case(tmp_path)
    _volume, staging, candidate, proc, writer, runtime, _current, prior = case

    with pytest.raises(
        b5.StagingQuarantineBlocked,
        match="current container inventory is malformed",
    ):
        b5.evaluate_and_quarantine(
            writer_receipt=writer,
            runtime_receipt=runtime,
            cleanup_candidate=candidate,
            process_scan_receipt=prior,
            container_provider=lambda: {"not": "a list"},
            proc_root=proc,
            boot_id="boot-123",
        )
    assert staging.exists()


def test_atomic_rename_failure_retains_source(tmp_path, monkeypatch):
    case = _case(tmp_path)
    staging, candidate = case[1], case[2]

    def fail(*_args, **_kwargs):
        raise OSError(17, "exists")

    monkeypatch.setattr(b5, "_rename_noreplace", fail)
    with pytest.raises(b5.StagingQuarantineBlocked, match="rename failed"):
        _evaluate(case)
    quarantine = staging.parent / b5._quarantine_name(candidate["candidate_sha256"])
    assert staging.exists()
    assert not quarantine.exists()


def test_atomic_noreplace_never_overwrites_existing_target(tmp_path):
    directory = tmp_path / "atomic"
    directory.mkdir()
    source = directory / "source"
    target = directory / "target"
    source.write_bytes(b"source-bytes")
    target.write_bytes(b"target-bytes")
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(OSError):
            b5._rename_noreplace(descriptor, source.name, target.name)
    finally:
        os.close(descriptor)
    assert source.read_bytes() == b"source-bytes"
    assert target.read_bytes() == b"target-bytes"


def test_directory_fsync_failure_is_recoverable_without_data_loss(
    tmp_path, monkeypatch
):
    case = _case(tmp_path)
    staging, candidate = case[1], case[2]
    quarantine = staging.parent / b5._quarantine_name(candidate["candidate_sha256"])
    original_fsync = b5.os.fsync
    calls = 0

    def fail_first(_descriptor):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("simulated directory fsync failure")
        return original_fsync(_descriptor)

    monkeypatch.setattr(b5.os, "fsync", fail_first)
    with pytest.raises(b5.StagingQuarantineBlocked, match="rename failed"):
        _evaluate(case)

    assert not staging.exists()
    assert quarantine.read_bytes() == b"owned staging bytes"

    monkeypatch.setattr(b5.os, "fsync", original_fsync)
    receipt = _evaluate(case)
    assert receipt["recovered_existing_quarantine"] is True
    assert receipt["mutation_performed_by_this_run"] is False
    assert quarantine.read_bytes() == b"owned staging bytes"


def test_same_boot_recovery_from_post_rename_crash_is_idempotent(tmp_path):
    case = _case(tmp_path)
    staging, candidate = case[1], case[2]
    quarantine = staging.parent / b5._quarantine_name(candidate["candidate_sha256"])
    original = _identity(staging)
    os.rename(staging, quarantine)

    receipt = _evaluate(case)

    assert not staging.exists()
    assert _identity(quarantine) == original
    assert receipt["recovered_existing_quarantine"] is True
    assert receipt["mutation_performed_by_this_run"] is False
    assert receipt["pre_quarantine_scan_passes"] == 0
    assert receipt["post_quarantine_scan_passes"] == 2


def test_recovery_rejects_both_names_even_if_same_inode(tmp_path):
    case = _case(tmp_path)
    staging, candidate = case[1], case[2]
    quarantine = staging.parent / b5._quarantine_name(candidate["candidate_sha256"])
    os.link(staging, quarantine)
    with pytest.raises(b5.StagingQuarantineBlocked, match="both exist"):
        _evaluate(case)


def test_recovery_rejects_foreign_quarantine_when_source_is_absent(tmp_path):
    case = _case(tmp_path)
    staging, candidate = case[1], case[2]
    quarantine = staging.parent / b5._quarantine_name(candidate["candidate_sha256"])
    staging.unlink()
    quarantine.write_bytes(b"foreign")
    with pytest.raises(b5.StagingQuarantineBlocked, match="identity changed"):
        _evaluate(case)


def test_post_rename_reference_race_blocks_receipt_but_preserves_quarantine(
    tmp_path, monkeypatch
):
    case = _case(tmp_path)
    staging, candidate, proc = case[1], case[2], case[3]
    quarantine = staging.parent / b5._quarantine_name(candidate["candidate_sha256"])
    original_rename = b5._rename_noreplace

    def rename_then_open_reference(directory, source, destination):
        original_rename(directory, source, destination)
        link = proc / "100" / "task" / "100" / "fd" / "9"
        link.symlink_to(quarantine)

    monkeypatch.setattr(b5, "_rename_noreplace", rename_then_open_reference)
    with pytest.raises(b5.StagingQuarantineBlocked, match="post-quarantine"):
        _evaluate(case)

    assert not staging.exists()
    assert quarantine.exists()
    (proc / "100" / "task" / "100" / "fd" / "9").unlink()
    monkeypatch.setattr(b5, "_rename_noreplace", original_rename)
    receipt = _evaluate(case)
    assert receipt["recovered_existing_quarantine"] is True


def test_final_appearance_blocks_before_quarantine(tmp_path):
    case = _case(tmp_path)
    staging, candidate = case[1], case[2]
    (staging.parent / candidate["final_name"]).write_bytes(b"unexpected")
    with pytest.raises(b5.StagingQuarantineBlocked, match="final entry changed"):
        _evaluate(case)
    assert staging.exists()


def test_create_only_private_candidate_bound_receipt(tmp_path):
    case = _case(tmp_path)
    value = _evaluate(case)
    digest = value["candidate_sha256"]
    root = tmp_path / "receipts"
    root.mkdir(mode=0o700)
    path = b5._write_private(root, digest, value)
    assert path == root / f"{digest}.json"
    assert json.loads(path.read_text()) == value
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    with pytest.raises(b5.StagingQuarantineBlocked, match="already exists"):
        b5._write_private(root, digest, value)


def test_private_receipt_rejects_content_digest_or_candidate_mismatch(tmp_path):
    case = _case(tmp_path)
    value = _evaluate(case)
    digest = value["candidate_sha256"]
    root = tmp_path / "receipts"
    root.mkdir(mode=0o700)

    tampered = dict(value)
    tampered["cleanup_authorized"] = True
    with pytest.raises(b5.StagingQuarantineBlocked, match="boundary is invalid"):
        b5._write_private(root, digest, tampered)

    with pytest.raises(b5.StagingQuarantineBlocked, match="boundary is invalid"):
        b5._write_private(root, "f" * 64, value)


def test_receipt_state_root_must_preexist_and_be_private(tmp_path):
    missing = tmp_path / "missing"
    with pytest.raises(b5.StagingQuarantineBlocked, match="unavailable"):
        b5._write_private(missing, "b" * 64, {"ok": True})

    public = tmp_path / "public"
    public.mkdir(mode=0o700)
    public.chmod(0o755)
    with pytest.raises(b5.StagingQuarantineBlocked, match="not private"):
        b5._write_private(public, "c" * 64, {"ok": True})


def test_receipt_state_root_parent_symlink_is_rejected(tmp_path):
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir(mode=0o700)
    private = real_parent / "state"
    private.mkdir(mode=0o700)
    link_parent = tmp_path / "linked-parent"
    link_parent.symlink_to(real_parent, target_is_directory=True)
    with pytest.raises(
        b5.StagingQuarantineBlocked,
        match="descriptor chain is unavailable",
    ):
        b5._write_private(link_parent / "state", "e" * 64, {"ok": True})


def test_receipt_state_root_symlink_is_rejected(tmp_path):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    link = tmp_path / "link"
    link.symlink_to(private, target_is_directory=True)
    with pytest.raises(
        b5.StagingQuarantineBlocked, match="descriptor chain is unavailable"
    ):
        b5._write_private(link, "d" * 64, {"ok": True})
