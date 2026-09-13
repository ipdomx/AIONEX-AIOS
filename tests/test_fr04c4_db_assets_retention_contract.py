from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKUP_WORKER = ROOT / "web-dashboard" / "backend" / "app" / "services" / "backup_worker.py"
SNAPSHOT = ROOT / "web-dashboard" / "backend" / "app" / "services" / "three_d_asset_backup.py"
RECEIPT = ROOT / "docs" / "project" / "receipts" / "FR-04C4-db-assets-retention-contract.md"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_fr04c4_platform_backup_pairs_database_and_asset_snapshot() -> None:
    worker = _text(BACKUP_WORKER)
    execute = worker.split("async def execute_backup", 1)[1].split("async def _finish_backup_failure", 1)[0]
    assert 'snapshot_required = scope == "platform" and self._three_d_executor.enabled' in execute
    assert "artifact = await self._executor.create_backup" in execute
    assert "self._three_d_executor.create_snapshot" in execute
    assert "artifact.location" in execute
    assert execute.index("artifact = await self._executor.create_backup") < execute.index("self._three_d_executor.create_snapshot")
    assert '"three_d_snapshot": snapshot_evidence' in execute
    assert 'snapshot_evidence["roots"] = snapshot.roots' in execute


def test_fr04c4_restore_validation_requires_and_validates_snapshot_evidence() -> None:
    worker = _text(BACKUP_WORKER)
    restore = worker.split("async def execute_restore_validation", 1)[1].split("async def _finish_restore_failure", 1)[0]
    assert 'snapshot_required = (' in restore
    assert 'backup.scope == "platform" and self._three_d_executor.enabled' in restore
    assert 'snapshot_evidence.get("required") is not True' in restore
    assert '"The selected platform backup has no durable 3D snapshot evidence"' in restore
    assert 'expected_snapshot_checksum = str(snapshot_evidence["checksum"])' in restore
    assert 'expected_snapshot_size = int(snapshot_evidence["size_bytes"])' in restore
    assert 'expected_snapshot_files = int(snapshot_evidence["file_count"])' in restore
    assert 'expected_snapshot_payload = int(snapshot_evidence["payload_bytes"])' in restore
    assert "self._three_d_executor.validate_snapshot" in restore
    assert 'validation_details["asset_snapshot_roots"] = snapshot_validation.roots' in restore


def test_fr04c4_retention_deletes_snapshot_and_database_as_one_unit() -> None:
    worker = _text(BACKUP_WORKER)
    retention = worker.split("async def _delete_expired_artifact", 1)[1].split("async def _apply_retention", 1)[0]
    assert "protected_reference" in retention
    assert "restore-validation" in retention
    assert 'record.status = "expired"' in retention
    assert "self._three_d_executor.delete_snapshot" in retention
    assert "self._executor.delete_artifact" in retention
    assert retention.index("self._three_d_executor.delete_snapshot") < retention.index("self._executor.delete_artifact")
    assert "record.location = None" in retention
    assert "Keep checksum, byte size, timestamps, and audit rows as durable" in retention


def test_fr04c4_uncommitted_cleanup_removes_companion_and_database_artifacts() -> None:
    worker = _text(BACKUP_WORKER)
    cleanup = worker.split("async def _cleanup_uncommitted_backup", 1)[1].split("async def execute_backup", 1)[0]
    assert "self._three_d_executor.delete_snapshot" in cleanup
    assert "self._executor.delete_artifact" in cleanup
    assert cleanup.index("self._three_d_executor.delete_snapshot") < cleanup.index("self._executor.delete_artifact")


def test_fr04c4_snapshot_validation_checks_root_totals_and_member_integrity() -> None:
    snapshot = _text(SNAPSHOT)
    assert 'manifest.get("file_count") != len(files)' in snapshot
    assert 'len(files) != int(expected_file_count)' in snapshot
    assert 'root_id not in declared_root_map' in snapshot
    assert 'relative.parts[0] != root_id' in snapshot
    assert 'file_member.size != expected_size' in snapshot
    assert 'digest.hexdigest(), expected_hash' in snapshot
    assert 'root_total["file_count"] += 1' in snapshot
    assert 'root_total["payload_bytes"] += count' in snapshot


def test_fr04c4_receipt_records_no_runtime_change() -> None:
    receipt = _text(RECEIPT)
    assert "No runtime code change" in receipt
    assert "DB dump and companion asset snapshot as one logical backup unit" in receipt
    assert "FR-04D non-empty backup acceptance" in receipt
