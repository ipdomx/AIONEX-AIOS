"""Regression contracts for backup retention and restore enqueue locking."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from app.api.v1.endpoints import backups as backup_endpoints
from app.core.auth import UserRecord
from app.db.models import BackupRecord
from fastapi import HTTPException


class RecordingSession:
    def __init__(
        self, scalar_results: list[Any], events: list[tuple[str, Any]]
    ) -> None:
        self.scalar_results = scalar_results
        self.events = events
        self.added: list[Any] = []
        self.flushes = 0
        self.commits = 0

    async def scalar(self, statement: Any) -> Any:
        self.events.append(("scalar", statement))
        return self.scalar_results.pop(0)

    def add(self, value: Any) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        self.flushes += 1

    async def commit(self) -> None:
        self.commits += 1


def _owner() -> UserRecord:
    return UserRecord(
        id="owner-1",
        email="owner@example.com",
        name="Owner",
        role="Super Owner",
        password_hash="unused",
        organization_id="organization-1",
        organization_name="AIONEX",
        organization_plan="enterprise",
        permissions=[],
    )


def _completed_backup() -> BackupRecord:
    now = datetime.now(UTC)
    return BackupRecord(
        id="backup-1",
        kind="on-demand",
        scope="platform",
        status="completed",
        location="/var/lib/aionex/backups/backup-" + ("a" * 24) + ".dump",
        checksum="b" * 64,
        size_bytes=4096,
        completed_at=now,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("backup_id", "operation"),
    [
        ("backup-1", "restore_validation"),
        (None, "test"),
    ],
)
async def test_restore_enqueue_locks_queue_before_backup_row(
    monkeypatch: pytest.MonkeyPatch,
    backup_id: str | None,
    operation: str,
) -> None:
    events: list[tuple[str, Any]] = []
    backup = _completed_backup()
    session = RecordingSession([backup, None], events)

    async def acquire_lock(_session: Any, key: str) -> None:
        events.append(("advisory-lock", key))

    monkeypatch.setattr(
        backup_endpoints,
        "acquire_enqueue_lock",
        acquire_lock,
    )

    selected, run = await backup_endpoints._enqueue_restore_validation(
        backup_id=backup_id,
        operation=operation,
        actor=_owner(),
        session=session,  # type: ignore[arg-type]
    )

    assert selected is backup
    assert run.details["backup_id"] == backup.id
    assert events[0] == ("advisory-lock", "restore-validation")
    assert events[1][0] == "scalar"
    assert events[1][1]._for_update_arg is not None
    assert session.flushes == 1
    assert session.commits == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("backup_id", ["backup-1", None])
async def test_restore_enqueue_revalidates_backup_after_advisory_lock(
    monkeypatch: pytest.MonkeyPatch,
    backup_id: str | None,
) -> None:
    events: list[tuple[str, Any]] = []
    backup = _completed_backup()
    session = RecordingSession([backup], events)

    async def retention_wins_before_lock(_session: Any, key: str) -> None:
        events.append(("advisory-lock", key))
        backup.status = "expired"
        backup.location = None

    monkeypatch.setattr(
        backup_endpoints,
        "acquire_enqueue_lock",
        retention_wins_before_lock,
    )

    with pytest.raises(HTTPException) as error:
        await backup_endpoints._enqueue_restore_validation(
            backup_id=backup_id,
            operation="restore_validation" if backup_id else "test",
            actor=_owner(),
            session=session,  # type: ignore[arg-type]
        )

    assert error.value.status_code == 409
    assert events[0] == ("advisory-lock", "restore-validation")
    assert events[1][1]._for_update_arg is not None
    assert session.flushes == 0
    assert session.commits == 0
