"""Export one fail-closed Studio drain input bundle from PostgreSQL.

This module is read-only. It sandwiches the Studio/backup observations between
closed-admission reads and refuses output if the operation or generation changes.
It performs no commit, cleanup, retry, admission transition, or filesystem I/O.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any
from uuid import UUID

from app.db.base import SessionLocal
from app.services import host_maintenance_admission as admission
from app.services import host_maintenance_cycles as cycles
from app.services import studio_resource_registry as studio_registry

SCHEMA = "aionex.studio-drain-inputs.v1"


class StudioDrainInputUnavailable(RuntimeError):
    """The requested closed-authority snapshot bundle cannot be proven stable."""


def _uuid(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False


def _authority(value: admission.HostMaintenanceSnapshot) -> dict[str, Any]:
    return {
        "schema_version": value.schema_version,
        "scope": value.scope,
        "generation": value.generation,
        "status": value.status,
        "enabled": value.enabled,
        "operation_id": value.operation_id,
        "reason": value.reason,
        "changed_at": value.changed_at.isoformat() if value.changed_at else None,
        "full_host_closure": value.full_host_closure,
    }


def _authority_key(value: admission.HostMaintenanceSnapshot) -> tuple[Any, ...]:
    return (
        value.schema_version,
        value.scope,
        value.generation,
        value.status,
        value.enabled,
        value.operation_id,
        value.reason,
        value.changed_at,
        value.full_host_closure,
    )


def _backup(value: cycles.CycleSnapshot) -> dict[str, Any]:
    return {
        "scope": value.scope,
        "observed_at": value.observed_at.isoformat(),
        "operation_id": value.authority.operation_id,
        "generation": value.authority.generation,
        "active_count": value.active_count,
        "unresolved_count": value.unresolved_count,
        "expired_count": value.expired_count,
        "unfinished_count": value.unfinished_count,
        "coverage_unverified": value.coverage_unverified,
        "full_host_closure": value.full_host_closure,
    }


async def collect_inputs(*, operation_id: str, expected_generation: int) -> dict[str, Any]:
    if not _uuid(operation_id) or type(expected_generation) is not int or expected_generation < 7:
        raise ValueError("canonical operation UUID and Studio generation are required")

    async with SessionLocal() as session:
        async with session.begin():
            before = await admission.read_admission_snapshot(
                session, required_scope="studio_job_requests"
            )
    if (
        before.is_open
        or before.operation_id != operation_id
        or before.generation != expected_generation
    ):
        raise StudioDrainInputUnavailable("Studio drain export requires current closed authority")

    studio = await studio_registry.execution_snapshot(session_factory=SessionLocal)
    if (
        studio.get("scope") != "studio_execution_threads"
        or studio.get("admission_closed") is not True
        or studio.get("coverage_unverified") is not True
        or studio.get("full_host_closure") is not False
    ):
        raise StudioDrainInputUnavailable("Studio snapshot boundary is invalid")

    async with SessionLocal() as session:
        async with session.begin():
            backup = await cycles.snapshot_backup_cycles(
                session,
                operation_id=operation_id,
                expected_generation=expected_generation,
            )
            after = await admission.read_admission_snapshot(
                session, required_scope="studio_job_requests"
            )

    async with SessionLocal() as session:
        async with session.begin():
            final = await admission.read_admission_snapshot(
                session, required_scope="studio_job_requests"
            )

    expected = _authority_key(before)
    if (
        _authority_key(backup.authority) != expected
        or _authority_key(after) != expected
        or _authority_key(final) != expected
    ):
        raise StudioDrainInputUnavailable("maintenance authority changed during snapshot collection")

    return {
        "schema": SCHEMA,
        "admission": _authority(before),
        "studio": studio,
        "backup": _backup(backup),
    }


async def async_main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--generation", type=int, required=True)
    args = parser.parse_args()
    try:
        payload = await collect_inputs(
            operation_id=args.operation_id,
            expected_generation=args.generation,
        )
    except (ValueError, StudioDrainInputUnavailable):
        print("FR06D8C4_STUDIO_DRAIN_INPUTS_BLOCKED")
        return 2
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(async_main()))
