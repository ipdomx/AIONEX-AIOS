"""FR-06D8C4B3 Studio process-reference scan acceptance."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/security/fr06d8c4_studio_process_scan.py"

_spec = importlib.util.spec_from_file_location("fr06d8c4_process_scan", SCRIPT)
assert _spec is not None and _spec.loader is not None
scan = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan)

VOLUME = "/var/lib/docker/volumes/web-dashboard_studio_asset_data/_data"


def _digest(value):
    body = {key: item for key, item in value.items() if key != "receipt_sha256"}
    value["receipt_sha256"] = scan._sha(body)
    return value


def _writer():
    return _digest({
        "schema": scan.WRITER_SCHEMA,
        "observed_at": "2026-09-20T01:00:00+00:00",
        "merge_sha": "a" * 40,
        "admission": {
            "operation_id": "11111111-1111-4111-8111-111111111111",
            "generation": 21,
        },
        "studio_snapshot": {"scope": "studio_execution_threads"},
        "writers": [
            {
                "service": "backend",
                "container_id": "backend-id",
                "started_at": "2026-09-20T00:59:00+00:00",
                "restart_count": 0,
            },
            {
                "service": "studio-worker",
                "container_id": "studio-id",
                "started_at": "2026-09-20T00:59:30+00:00",
                "restart_count": 0,
            },
        ],
        "readers": [
            {
                "service": "backup-worker",
                "container_id": "backup-id",
                "started_at": "2026-09-20T00:58:00+00:00",
                "restart_count": 0,
            }
        ],
        "studio_volume_source": VOLUME,
        "application_writer_epoch_verified": True,
        "process_drain_verified": False,
        "host_process_scan_verified": False,
        "backup_cycle_drain_verified": False,
        "cleanup_authorized": False,
        "filesystem_mutation_performed": False,
        "full_host_closure": False,
    })


def _runtime(writer=None):
    writer = writer or _writer()
    return _digest({
        "schema": scan.RUNTIME_SCHEMA,
        "observed_at": "2026-09-20T01:01:00+00:00",
        "writer_receipt_sha256": writer["receipt_sha256"],
        "merge_sha": writer["merge_sha"],
        "operation_id": writer["admission"]["operation_id"],
        "generation": writer["admission"]["generation"],
        "studio_volume_source": writer["studio_volume_source"],
        "writer_container_ids": sorted(
            row["container_id"] for row in writer["writers"]
        ),
        "backup_snapshot_sha256": "b" * 64,
        "application_writer_epoch_verified": True,
        "runtime_container_epoch_stable": True,
        "backup_cycle_drain_verified": True,
        "process_drain_verified": False,
        "host_process_scan_verified": False,
        "cleanup_authorized": False,
        "filesystem_mutation_performed": False,
        "full_host_closure": False,
    })


def _container(service, identifier, *, rw=None, started=None):
    mounts = []
    if rw is not None:
        mounts.append({
            "Destination": scan.DESTINATION,
            "Source": VOLUME,
            "RW": rw,
            "Type": "volume",
            "Name": "web-dashboard_studio_asset_data",
        })
    defaults = {
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
            "StartedAt": started or defaults.get(
                service, "2026-09-20T00:57:00+00:00"
            ),
        },
        "Mounts": mounts,
    }


def _containers():
    return [
        _container("backend", "backend-id", rw=True),
        _container("studio-worker", "studio-id", rw=True),
        _container("backup-worker", "backup-id", rw=False),
        _container("communication-worker", "comm-id"),
    ]


def _scan_evidence():
    return {
        "scan_passes": 2,
        "inventory_entries": 7,
        "inventory_sha256": "c" * 64,
        "visible_reference_count": 0,
    }


def test_evaluate_accepts_scoped_zero_reference_scan_without_claiming_host_drain():
    writer = _writer()
    receipt = scan.evaluate(
        writer_receipt=writer,
        runtime_receipt=_runtime(writer),
        containers=_containers(),
        scan=_scan_evidence(),
        boot_id="boot-123",
    )
    assert receipt["host_visible_studio_reference_scan_verified"] is True
    assert receipt["studio_process_drain_verified"] is True
    assert receipt["backup_cycle_drain_verified"] is True
    assert receipt["process_drain_verified"] is False
    assert receipt["cleanup_authorized"] is False
    assert receipt["filesystem_mutation_performed"] is False
    assert receipt["full_host_closure"] is False
    assert len(receipt["receipt_sha256"]) == 64


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("scan_passes", 1),
        ("inventory_entries", 0),
        ("inventory_sha256", "short"),
        ("visible_reference_count", 1),
    ],
)
def test_incomplete_process_scan_evidence_is_rejected(field, value):
    evidence = _scan_evidence()
    evidence[field] = value
    writer = _writer()
    with pytest.raises(scan.ProcessScanBlocked, match="evidence is incomplete"):
        scan.evaluate(
            writer_receipt=writer,
            runtime_receipt=_runtime(writer),
            containers=_containers(),
            scan=evidence,
            boot_id="boot-123",
        )


def test_changed_writer_epoch_is_rejected():
    containers = _containers()
    containers[0]["Id"] = "replacement-backend"
    writer = _writer()
    with pytest.raises(scan.ProcessScanBlocked, match="writer epoch changed"):
        scan.evaluate(
            writer_receipt=writer,
            runtime_receipt=_runtime(writer),
            containers=containers,
            scan=_scan_evidence(),
            boot_id="boot-123",
        )


def test_tampered_runtime_receipt_is_rejected():
    writer = _writer()
    runtime = _runtime(writer)
    runtime["cleanup_authorized"] = True
    with pytest.raises(scan.ProcessScanBlocked, match="digest differs"):
        scan.evaluate(
            writer_receipt=writer,
            runtime_receipt=runtime,
            containers=_containers(),
            scan=_scan_evidence(),
            boot_id="boot-123",
        )


def test_blank_boot_id_is_rejected():
    writer = _writer()
    with pytest.raises(scan.ProcessScanBlocked, match="boot id"):
        scan.evaluate(
            writer_receipt=writer,
            runtime_receipt=_runtime(writer),
            containers=_containers(),
            scan=_scan_evidence(),
            boot_id="   ",
        )


def test_inventory_rejects_symlink_inside_studio_volume(tmp_path):
    root = tmp_path / "studio"
    root.mkdir()
    target = tmp_path / "outside"
    target.write_text("outside")
    (root / "unsafe").symlink_to(target)
    with pytest.raises(scan.ProcessScanBlocked, match="unsafe entry type"):
        scan._inventory(root)


def test_inventory_is_stable_for_regular_tree(tmp_path):
    root = tmp_path / "studio"
    child = root / "tenant" / "asset"
    child.mkdir(parents=True)
    (child / "archive.zip").write_bytes(b"archive")
    first = scan._inventory(root)
    second = scan._inventory(root)
    assert first == second
    assert "." in first
    assert "tenant/asset/archive.zip" in first
    assert len(scan._reference_identities(first)) == len(first)


def _fake_proc(tmp_path, reference_target=None):
    proc = tmp_path / "proc"
    thread = proc / "123" / "task" / "123"
    fd = thread / "fd"
    maps = proc / "123" / "map_files"
    fd.mkdir(parents=True)
    maps.mkdir(parents=True)
    if reference_target is not None:
        (fd / "5").symlink_to(reference_target)
    return proc


def test_proc_scan_finds_visible_fd_reference(tmp_path):
    volume = tmp_path / "studio"
    volume.mkdir()
    archive = volume / "archive.zip"
    archive.write_bytes(b"owned")
    identities = scan._reference_identities(scan._inventory(volume))
    proc = _fake_proc(tmp_path, archive)
    holders = scan._scan_proc(identities, proc_root=proc)
    assert holders == [{"kind": "fd", "pid": 123, "tid": 123, "identifier": "5"}]


def test_proc_scan_returns_empty_without_studio_reference(tmp_path):
    volume = tmp_path / "studio"
    volume.mkdir()
    (volume / "archive.zip").write_bytes(b"owned")
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"other")
    identities = scan._reference_identities(scan._inventory(volume))
    proc = _fake_proc(tmp_path, outside)
    assert scan._scan_proc(identities, proc_root=proc) == []


def test_host_scan_requires_two_stable_zero_holder_passes(tmp_path, monkeypatch):
    volume = tmp_path / "studio"
    volume.mkdir()
    (volume / "archive.zip").write_bytes(b"owned")
    calls = []

    def empty(identities):
        calls.append(len(identities))
        return []

    monkeypatch.setattr(scan, "_scan_proc", empty)
    evidence = scan._host_scan(volume)
    assert calls and len(calls) == 2
    assert evidence["scan_passes"] == 2
    assert evidence["visible_reference_count"] == 0


def test_host_scan_blocks_visible_reference(tmp_path, monkeypatch):
    volume = tmp_path / "studio"
    volume.mkdir()
    (volume / "archive.zip").write_bytes(b"owned")
    monkeypatch.setattr(
        scan,
        "_scan_proc",
        lambda identities: [{"kind": "fd", "pid": 1, "tid": 1, "identifier": "7"}],
    )
    with pytest.raises(scan.ProcessScanBlocked, match="references remain"):
        scan._host_scan(volume)


def test_cli_writes_private_immutable_receipt(tmp_path, monkeypatch):
    writer = _writer()
    runtime = _runtime(writer)
    writer_path = tmp_path / "writer.json"
    runtime_path = tmp_path / "runtime.json"
    output = tmp_path / "scan.json"
    writer_path.write_text(json.dumps(writer))
    runtime_path.write_text(json.dumps(runtime))

    monkeypatch.setattr(scan, "_containers", _containers)
    monkeypatch.setattr(scan, "_host_scan", lambda root: _scan_evidence())
    monkeypatch.setattr(
        scan.Path,
        "read_text",
        scan.Path.read_text,
    )
    original_read_text = scan.Path.read_text

    def read_text(path, *args, **kwargs):
        if str(path) == "/proc/sys/kernel/random/boot_id":
            return "boot-123\n"
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(scan.Path, "read_text", read_text)
    monkeypatch.setattr(
        __import__("sys"),
        "argv",
        [
            str(SCRIPT),
            "--writer-receipt",
            str(writer_path),
            "--runtime-receipt",
            str(runtime_path),
            "--output",
            str(output),
        ],
    )
    assert scan.main() == 0
    prior = json.loads(output.read_text())
    assert prior["studio_process_drain_verified"] is True
    assert prior["cleanup_authorized"] is False
    assert output.stat().st_mode & 0o777 == 0o600
    assert scan.main() == 2
    assert json.loads(output.read_text()) == prior


def test_unexpected_current_writer_mount_is_rejected():
    containers = _containers() + [
        _container("rogue-writer", "rogue-id", rw=True)
    ]
    writer = _writer()
    with pytest.raises(scan.ProcessScanBlocked, match="unexpected current Studio writer"):
        scan.evaluate(
            writer_receipt=writer,
            runtime_receipt=_runtime(writer),
            containers=containers,
            scan=_scan_evidence(),
            boot_id="boot-123",
        )


def test_changed_reader_epoch_is_rejected():
    containers = _containers()
    containers[2]["Id"] = "replacement-backup"
    writer = _writer()
    with pytest.raises(scan.ProcessScanBlocked, match="reader epoch changed"):
        scan.evaluate(
            writer_receipt=writer,
            runtime_receipt=_runtime(writer),
            containers=containers,
            scan=_scan_evidence(),
            boot_id="boot-123",
        )


def test_running_one_shot_initializer_is_rejected():
    containers = _containers() + [
        _container("backup-asset-root-init", "init-id", rw=True)
    ]
    writer = _writer()
    with pytest.raises(scan.ProcessScanBlocked, match="initializer is running"):
        scan.evaluate(
            writer_receipt=writer,
            runtime_receipt=_runtime(writer),
            containers=containers,
            scan=_scan_evidence(),
            boot_id="boot-123",
        )


def test_host_scan_blocks_inventory_change_between_passes(tmp_path, monkeypatch):
    volume = tmp_path / "studio"
    volume.mkdir()
    archive = volume / "archive.zip"
    archive.write_bytes(b"owned")
    first = scan._inventory(volume)
    changed = dict(first)
    changed["archive.zip"] = tuple(
        value + 1 if index == 7 else value
        for index, value in enumerate(first["archive.zip"])
    )
    snapshots = iter((first, changed))
    monkeypatch.setattr(scan, "_inventory", lambda root: next(snapshots))
    monkeypatch.setattr(scan, "_scan_proc", lambda identities: [])
    with pytest.raises(scan.ProcessScanBlocked, match="changed during first process scan"):
        scan._host_scan(volume)
