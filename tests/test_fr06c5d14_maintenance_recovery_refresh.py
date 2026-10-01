from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "fr06c5d14_maintenance_recovery_refresh",
    ROOT / "scripts/security/fr06c5d14_maintenance_recovery_refresh.py",
)
assert SPEC and SPEC.loader
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)

OP = "cd5a0e31-a49b-4fdf-b2a6-ac53a7831d17"
GEN = 42


def authority():
    return {
        "schema_version": 8,
        "scope": "all-eight-scopes",
        "generation": GEN,
        "status": "open",
        "enabled": True,
        "operation_id": OP,
        "full_host_closure": False,
    }


def patch_root(monkeypatch, tmp_path: Path):
    def open_root(path: Path):
        path.mkdir(parents=True, exist_ok=True)
        os.chmod(path, 0o700)
        return os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    monkeypatch.setattr(m, "_journal_root", open_root)
    monkeypatch.setattr(m, "_source", lambda: {"source_commit": "a" * 40})


def backup_state(backup_id="backup-1", *, status="completed"):
    return {
        "id": backup_id,
        "kind": f"fr06-c5d14-{OP[:8]}-g{GEN}",
        "scope": "platform",
        "status": status,
        "offsite_status": "completed" if status == "completed" else "pending",
        "offsite_encrypted": status == "completed",
        "checksum_present": status == "completed",
        "size_bytes": 12345 if status == "completed" else None,
        "created_at": "2026-10-01T06:00:00+00:00",
        "completed_at": "2026-10-01T06:00:10+00:00" if status == "completed" else None,
    }


def restore_state(restore_id="restore-1", *, status="completed"):
    return {
        "id": restore_id,
        "status": status,
        "created_at": "2026-10-01T06:00:11+00:00",
        "completed_at": "2026-10-01T06:00:20+00:00" if status == "completed" else None,
        "backup_id": "backup-1",
        "validated": status == "completed",
        "offsite_validated": status == "completed",
        "three_d_snapshot_validated": status == "completed",
        "offsite_three_d_snapshot_validated": status == "completed",
        "checksum_present": status == "completed",
        "checksums_match": status == "completed",
        "size_bytes": 12345 if status == "completed" else None,
        "scratch_databases": 0,
    }


def install_happy(monkeypatch, calls):
    monkeypatch.setattr(m, "_authority", lambda op, gen: authority())
    monkeypatch.setattr(
        m, "_enqueue_backup",
        lambda kind: calls.append(("backup", kind))
        or {"backup_id": "backup-1", "status": "pending"},
    )
    monkeypatch.setattr(m, "_find_backups", lambda kind: [])
    monkeypatch.setattr(m, "_backup_state", lambda bid: backup_state(bid))
    monkeypatch.setattr(
        m, "_enqueue_restore",
        lambda bid: calls.append(("restore", bid))
        or {"backup_id": bid, "restore_id": "restore-1", "status": "pending"},
    )
    monkeypatch.setattr(m, "_find_restores", lambda bid: [])
    monkeypatch.setattr(m, "_restore_state", lambda rid: restore_state(rid))


def test_one_backup_and_one_restore_are_journaled(monkeypatch, tmp_path):
    patch_root(monkeypatch, tmp_path)
    calls = []
    install_happy(monkeypatch, calls)
    result = m.execute(
        operation_id=OP, generation=GEN, journal_root=tmp_path / "journal"
    )
    assert calls == [
        ("backup", f"fr06-c5d14-{OP[:8]}-g{GEN}"),
        ("restore", "backup-1"),
    ]
    assert result["fresh_recovery_verified"] is True
    assert result["restore_offsite_validated"] is True
    assert result["in_place_restore"] is False
    root = tmp_path / "journal"
    for name in (
        "recovery-session-intent.json",
        "backup-enqueue-intent.json",
        "backup-enqueue-accepted.json",
        "backup-completed.json",
        "restore-enqueue-intent.json",
        "restore-enqueue-accepted.json",
        "restore-completed.json",
        "maintenance-recovery-accepted.json",
    ):
        assert (root / name).is_file()


def test_existing_backup_intent_reconciles_unique_record_without_replay(
    monkeypatch, tmp_path
):
    patch_root(monkeypatch, tmp_path)
    calls = []
    install_happy(monkeypatch, calls)
    root = tmp_path / "journal"
    fd = m._journal_root(root)
    try:
        m._write_new(
            fd,
            "recovery-session-intent.json",
            {
                "schema": m.SCHEMA,
                "operation_id": OP,
                "generation": GEN,
                "authority": authority(),
                "source": {"source_commit": "a" * 40},
                "backup_kind": f"fr06-c5d14-{OP[:8]}-g{GEN}",
                "scope": "platform",
                "in_place_restore": False,
                "automatic_retry": False,
            },
        )
        m._write_new(
            fd,
            "backup-enqueue-intent.json",
            {
                "operation_id": OP,
                "generation": GEN,
                "backup_kind": f"fr06-c5d14-{OP[:8]}-g{GEN}",
                "scope": "platform",
                "automatic_retry": False,
            },
        )
    finally:
        os.close(fd)
    monkeypatch.setattr(
        m, "_find_backups",
        lambda kind: [{"id": "backup-1", "status": "completed"}],
    )
    monkeypatch.setattr(
        m, "_enqueue_backup",
        lambda *_: (_ for _ in ()).throw(AssertionError("backup replay")),
    )
    result = m.execute(operation_id=OP, generation=GEN, journal_root=root)
    assert result["backup_id"] == "backup-1"
    assert calls == [("restore", "backup-1")]


def test_ambiguous_backup_intent_never_replays(monkeypatch, tmp_path):
    patch_root(monkeypatch, tmp_path)
    calls = []
    install_happy(monkeypatch, calls)
    root = tmp_path / "journal"
    fd = m._journal_root(root)
    try:
        m._write_new(
            fd,
            "recovery-session-intent.json",
            {
                "schema": m.SCHEMA,
                "operation_id": OP,
                "generation": GEN,
                "authority": authority(),
                "source": {"source_commit": "a" * 40},
                "backup_kind": f"fr06-c5d14-{OP[:8]}-g{GEN}",
                "scope": "platform",
                "in_place_restore": False,
                "automatic_retry": False,
            },
        )
        m._write_new(
            fd,
            "backup-enqueue-intent.json",
            {
                "operation_id": OP,
                "generation": GEN,
                "backup_kind": f"fr06-c5d14-{OP[:8]}-g{GEN}",
                "scope": "platform",
                "automatic_retry": False,
            },
        )
    finally:
        os.close(fd)
    monkeypatch.setattr(m, "_find_backups", lambda kind: [])
    monkeypatch.setattr(
        m, "_enqueue_backup",
        lambda *_: (_ for _ in ()).throw(AssertionError("backup replay")),
    )
    with pytest.raises(m.RecoveryRefreshHalted):
        m.execute(operation_id=OP, generation=GEN, journal_root=root)


def test_restore_intent_reconciles_unique_record_without_replay(monkeypatch, tmp_path):
    patch_root(monkeypatch, tmp_path)
    calls = []
    install_happy(monkeypatch, calls)
    root = tmp_path / "journal"
    first = m.execute(operation_id=OP, generation=GEN, journal_root=root)
    assert first["restore_id"] == "restore-1"
    # Remove only the accepted restore/result evidence to model output loss after enqueue.
    for name in (
        "restore-enqueue-accepted.json",
        "restore-completed.json",
        "maintenance-recovery-accepted.json",
    ):
        (root / name).unlink()
    monkeypatch.setattr(
        m, "_find_restores",
        lambda bid: [{"id": "restore-1", "status": "completed"}],
    )
    monkeypatch.setattr(
        m, "_enqueue_restore",
        lambda *_: (_ for _ in ()).throw(AssertionError("restore replay")),
    )
    calls.clear()
    again = m.execute(operation_id=OP, generation=GEN, journal_root=root)
    assert again["restore_id"] == "restore-1"
    assert calls == []


def test_failed_durable_job_is_not_reenqueued(monkeypatch, tmp_path):
    patch_root(monkeypatch, tmp_path)
    calls = []
    install_happy(monkeypatch, calls)
    monkeypatch.setattr(
        m, "_backup_state", lambda bid: backup_state(bid, status="failed")
    )
    with pytest.raises(m.RecoveryRefreshHalted):
        m.execute(
            operation_id=OP, generation=GEN, journal_root=tmp_path / "journal"
        )
    assert calls == [("backup", f"fr06-c5d14-{OP[:8]}-g{GEN}")]


@pytest.mark.parametrize(
    "changed",
    [
        {"generation": GEN + 1},
        {"status": "closed", "enabled": False},
        {"operation_id": "11111111-1111-1111-1111-111111111111"},
        {"full_host_closure": True},
    ],
)
def test_authority_reader_rejects_drift(monkeypatch, changed):
    current = authority()
    current.update(changed)
    monkeypatch.setattr(m, "_inside", lambda program: current)
    with pytest.raises(m.RecoveryRefreshHalted):
        m._authority(OP, GEN)



def test_completed_operator_is_read_only_on_repeat(monkeypatch, tmp_path):
    patch_root(monkeypatch, tmp_path)
    calls = []
    install_happy(monkeypatch, calls)
    root = tmp_path / "journal"
    first = m.execute(operation_id=OP, generation=GEN, journal_root=root)
    calls.clear()
    second = m.execute(operation_id=OP, generation=GEN, journal_root=root)
    assert second == first
    assert calls == []


def test_preexisting_backup_without_journal_blocks_duplicate(monkeypatch, tmp_path):
    patch_root(monkeypatch, tmp_path)
    calls = []
    install_happy(monkeypatch, calls)
    monkeypatch.setattr(
        m, "_find_backups", lambda kind: [{"id": "existing", "status": "completed"}]
    )
    with pytest.raises(m.RecoveryRefreshHalted):
        m.execute(
            operation_id=OP, generation=GEN, journal_root=tmp_path / "journal"
        )
    assert calls == []

def test_restore_must_validate_local_offsite_assets_and_cleanup(monkeypatch, tmp_path):
    patch_root(monkeypatch, tmp_path)
    calls = []
    install_happy(monkeypatch, calls)
    bad = restore_state()
    bad["offsite_validated"] = False
    monkeypatch.setattr(m, "_restore_state", lambda rid: bad)
    with pytest.raises(m.RecoveryRefreshHalted):
        m.execute(
            operation_id=OP, generation=GEN, journal_root=tmp_path / "journal"
        )


def test_source_has_no_in_place_restore_or_admission_transition():
    source = (
        ROOT / "scripts/security/fr06c5d14_maintenance_recovery_refresh.py"
    ).read_text()
    assert "create_backup" in source
    assert "_enqueue_restore_validation" in source
    assert "open_admission" not in source
    assert "close_admission" not in source
    assert "dry_run=False" not in source
    assert "in_place_restore" in source
    assert "automatic_retry" in source
