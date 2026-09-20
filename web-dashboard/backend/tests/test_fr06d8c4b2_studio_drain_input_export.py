"""Source acceptance for the read-only Studio drain input exporter."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.services import host_maintenance_admission as admission
from app.services import host_maintenance_cycles as cycles
from app.services import studio_drain_input_export as export


OPERATION = "11111111-1111-4111-8111-111111111111"


def _authority(*, generation=14, status="closed", operation_id=OPERATION):
    return admission.HostMaintenanceSnapshot(
        schema_version=7,
        scope=admission.STUDIO_REQUEST_COVERAGE_SCOPE,
        generation=generation,
        status=status,
        enabled=status == "open",
        operation_id=operation_id,
        reason="isolated drain export",
        changed_at=datetime(2026, 9, 20, tzinfo=UTC),
        full_host_closure=False,
    )


def _backup(authority):
    return cycles.CycleSnapshot(
        authority=authority,
        observed_at=datetime(2026, 9, 20, 0, 1, tzinfo=UTC),
        cycles=(),
        active_count=0,
        unresolved_count=0,
        expired_count=0,
    )


def _studio():
    return {
        "scope": "studio_execution_threads",
        "observed_at": "2026-09-20T00:00:30+00:00",
        "executions": [],
        "postcrash_observations": [],
        "admission_closed": True,
        "coverage_unverified": True,
        "full_host_closure": False,
    }


class _Begin:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *_):
        return False


class _Session:
    def begin(self):
        return _Begin()


class _SessionContext:
    async def __aenter__(self):
        return _Session()

    async def __aexit__(self, *_):
        return False


def _factory():
    return _SessionContext()


@pytest.mark.asyncio
async def test_export_flattens_real_contract_without_mutation(monkeypatch):
    authority = _authority()
    reads = iter([authority, authority, authority])

    async def read(*_args, **_kwargs):
        return next(reads)

    async def studio(*_args, **_kwargs):
        return _studio()

    async def backup(*_args, **_kwargs):
        return _backup(authority)

    monkeypatch.setattr(export, "SessionLocal", _factory)
    monkeypatch.setattr(export.admission, "read_admission_snapshot", read)
    monkeypatch.setattr(export.studio_registry, "execution_snapshot", studio)
    monkeypatch.setattr(export.cycles, "snapshot_backup_cycles", backup)

    payload = await export.collect_inputs(
        operation_id=OPERATION,
        expected_generation=14,
    )
    assert payload["schema"] == export.SCHEMA
    assert payload["admission"]["operation_id"] == OPERATION
    assert payload["studio"] == _studio()
    assert payload["backup"] == {
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
    }


@pytest.mark.asyncio
async def test_authority_change_during_collection_fails_closed(monkeypatch):
    before = _authority()
    changed = _authority(generation=15)
    reads = iter([before, changed, changed])

    async def read(*_args, **_kwargs):
        return next(reads)

    async def studio(*_args, **_kwargs):
        return _studio()

    async def backup(*_args, **_kwargs):
        return _backup(before)

    monkeypatch.setattr(export, "SessionLocal", _factory)
    monkeypatch.setattr(export.admission, "read_admission_snapshot", read)
    monkeypatch.setattr(export.studio_registry, "execution_snapshot", studio)
    monkeypatch.setattr(export.cycles, "snapshot_backup_cycles", backup)

    with pytest.raises(export.StudioDrainInputUnavailable, match="changed"):
        await export.collect_inputs(
            operation_id=OPERATION,
            expected_generation=14,
        )


@pytest.mark.asyncio
async def test_open_authority_never_exports(monkeypatch):
    async def read(*_args, **_kwargs):
        return _authority(status="open")

    monkeypatch.setattr(export, "SessionLocal", _factory)
    monkeypatch.setattr(export.admission, "read_admission_snapshot", read)
    with pytest.raises(export.StudioDrainInputUnavailable, match="closed"):
        await export.collect_inputs(operation_id=OPERATION, expected_generation=14)


@pytest.mark.asyncio
async def test_invalid_identity_is_rejected_before_snapshot_access(monkeypatch):
    async def forbidden(*_args, **_kwargs):
        raise AssertionError("database read must not occur")

    monkeypatch.setattr(export.admission, "read_admission_snapshot", forbidden)
    with pytest.raises(ValueError):
        await export.collect_inputs(operation_id="not-a-uuid", expected_generation=14)
    with pytest.raises(ValueError):
        await export.collect_inputs(operation_id=OPERATION, expected_generation=6)
