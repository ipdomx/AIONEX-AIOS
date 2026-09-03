"""Fail-closed release and recovery gates for protected local 3D backup evidence."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from app.api.owner import control_plane, operations_integration
from app.db.models import BackupRecord, DisasterRecoveryRun, OwnerControlRecord
from app.services import security_release_gate


class _Rows:
    def __init__(self, values: list[Any]) -> None:
        self._values = values

    def all(self) -> list[Any]:
        return self._values


class _EvidenceSession:
    def __init__(
        self,
        backup: BackupRecord | None,
        restores: list[DisasterRecoveryRun],
    ) -> None:
        self.backup = backup
        self.restores = restores

    async def scalar(self, _statement: object) -> BackupRecord | None:
        return self.backup

    async def scalars(self, _statement: object) -> _Rows:
        return _Rows(self.restores)


def _backup() -> BackupRecord:
    return BackupRecord(
        id="platform-backup-3d-gate",
        kind="scheduled-production",
        scope="platform",
        status="completed",
        location="/protected/backup.dump",
        checksum="a" * 64,
        size_bytes=4096,
        completed_at=datetime.now(UTC),
    )


def _restore(backup: BackupRecord, *, three_d: bool) -> DisasterRecoveryRun:
    details: dict[str, Any] = {
        "backup_id": backup.id,
        "validated": True,
        "checksum": backup.checksum,
        "size_bytes": backup.size_bytes,
    }
    if three_d:
        details.update(
            {
                "three_d_snapshot_required": True,
                "three_d_snapshot_validated": True,
            }
        )
    return DisasterRecoveryRun(
        id="restore-3d-gate" if three_d else "restore-db-only",
        operation="restore_validation",
        status="completed",
        details=details,
        completed_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_owner_backup_gate_requires_three_d_restore_evidence_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backup = _backup()

    async def artifact_ready(
        _backup: BackupRecord | None,
        *,
        verify_checksum: bool,
    ) -> bool:
        assert verify_checksum is True
        return True

    monkeypatch.setattr(control_plane, "_backup_artifact_ready", artifact_ready)
    monkeypatch.setattr(control_plane.settings, "BACKUP_THREE_D_ASSETS_ENABLED", True)

    blocked = OwnerControlRecord(
        domain="release",
        resource_id="backup",
        status="pending",
        enabled=True,
        payload={"name": "Backup & Restore Verification"},
        version=1,
    )
    await control_plane._validate_release_gate(  # type: ignore[arg-type]
        _EvidenceSession(backup, [_restore(backup, three_d=False)]), blocked
    )
    assert blocked.status == "blocked"

    passed = OwnerControlRecord(
        domain="release",
        resource_id="backup",
        status="pending",
        enabled=True,
        payload={"name": "Backup & Restore Verification"},
        version=1,
    )
    result = await control_plane._validate_release_gate(  # type: ignore[arg-type]
        _EvidenceSession(backup, [_restore(backup, three_d=True)]), passed
    )
    assert passed.status == "passed"
    assert result["evidence"]["threeDAssetRecoveryRequired"] is True


@pytest.mark.asyncio
async def test_security_assurance_requires_three_d_restore_evidence_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backup = _backup()
    monkeypatch.setattr(
        security_release_gate.settings,
        "BACKUP_THREE_D_ASSETS_ENABLED",
        True,
    )

    legacy = await security_release_gate.operational_assurance(  # type: ignore[arg-type]
        _EvidenceSession(backup, [_restore(backup, three_d=False)])
    )
    assert legacy == {"recent_backup": True, "recent_dr_restore": False}

    protected = await security_release_gate.operational_assurance(  # type: ignore[arg-type]
        _EvidenceSession(backup, [_restore(backup, three_d=True)])
    )
    assert protected == {"recent_backup": True, "recent_dr_restore": True}


@pytest.mark.asyncio
async def test_operations_integration_requires_three_d_restore_evidence_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backup = _backup()
    monkeypatch.setattr(
        operations_integration.settings,
        "BACKUP_THREE_D_ASSETS_ENABLED",
        True,
    )

    assert not await operations_integration._restore_evidence_ready(  # type: ignore[arg-type]
        _EvidenceSession(backup, [_restore(backup, three_d=False)]), backup
    )
    assert await operations_integration._restore_evidence_ready(  # type: ignore[arg-type]
        _EvidenceSession(backup, [_restore(backup, three_d=True)]), backup
    )
