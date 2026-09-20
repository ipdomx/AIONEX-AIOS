"""Isolated PostgreSQL acceptance for FR-06C5D9A Realtime admission."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import UTC, datetime
import importlib.util
import os
from pathlib import Path
import re
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.schema import CreateSchema, DropSchema

from app.api.v1.endpoints import realtime_media
from app.db.base import Base
from app.db.models import OwnerControlRecord
from app.services import host_maintenance_admission as admission
from app.services.host_maintenance_admission import (
    HostMaintenanceClosed,
    HostMaintenanceUnavailable,
)
from app.services.host_maintenance_realtime_admission import (
    CONSUMER,
    require_realtime_admission,
)


def _migration(connection, direction: str = "upgrade") -> None:
    path = Path(__file__).resolve().parents[1] / (
        "alembic/versions/20260920_0063_realtime_media_admission.py"
    )
    spec = importlib.util.spec_from_file_location(
        "realtime_maintenance_" + uuid4().hex, path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.op = Operations(MigrationContext.configure(connection))
    getattr(module, direction)()


def _schema_seven(*, generation: int = 9) -> dict:
    return {
        "schema_version": 7,
        "scope": admission.STUDIO_REQUEST_COVERAGE_SCOPE,
        "generation": generation,
        "operation_id": str(uuid4()),
        "reason": "isolated-realtime-acceptance",
        "changed_at": datetime.now(UTC).isoformat(),
        "full_host_closure": False,
    }


@pytest_asyncio.fixture
async def realtime_gate_case():
    url = make_url(os.environ.get("DATABASE_URL", ""))
    assert url.drivername == "postgresql+asyncpg"
    assert re.search(
        r"(?:^|[_-])(?:test|pytest|ci|smoke|disposable)(?:[_-]|$)",
        url.database or "",
    )
    schema = "realtime_gate_" + uuid4().hex
    admin = create_async_engine(url, poolclass=NullPool)
    engine = create_async_engine(
        url,
        poolclass=NullPool,
        connect_args={"server_settings": {"search_path": schema}},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    authority_id = str(uuid4())
    created = False
    try:
        async with admin.begin() as connection:
            await connection.execute(CreateSchema(schema))
            created = True
        async with engine.begin() as connection:
            await connection.run_sync(
                lambda conn: Base.metadata.create_all(
                    conn, tables=[OwnerControlRecord.__table__]
                )
            )
        payload = _schema_seven()
        async with sessions() as session:
            session.add(
                OwnerControlRecord(
                    id=authority_id,
                    domain=admission.DOMAIN,
                    resource_id=admission.RESOURCE_ID,
                    status="open",
                    enabled=True,
                    payload=payload,
                    version=payload["generation"],
                )
            )
            await session.commit()
        yield SimpleNamespace(
            engine=engine,
            sessions=sessions,
            authority_id=authority_id,
            schema=schema,
        )
    finally:
        await engine.dispose()
        if created:
            async with admin.begin() as connection:
                await connection.execute(DropSchema(schema, cascade=True))
        await admin.dispose()


async def _authority(case):
    async with case.sessions() as session:
        row = await session.get(OwnerControlRecord, case.authority_id)
        return None if row is None else {
            "payload": deepcopy(row.payload),
            "version": row.version,
            "status": row.status,
            "enabled": row.enabled,
        }


@pytest.mark.asyncio
@pytest.mark.parametrize("closed", [False, True])
async def test_migration_preserves_state_and_widens_only_coverage(
    realtime_gate_case, closed
):
    case = realtime_gate_case
    async with case.sessions() as session:
        row = await session.get(OwnerControlRecord, case.authority_id)
        row.status = "closed" if closed else "open"
        row.enabled = not closed
        await session.commit()
    before = await _authority(case)
    async with case.engine.begin() as connection:
        await connection.run_sync(_migration)
    after = await _authority(case)
    assert after["version"] == before["version"] + 1
    assert after["payload"]["schema_version"] == 8
    assert after["payload"]["scope"] == admission.REALTIME_REQUEST_COVERAGE_SCOPE
    assert (after["status"], after["enabled"]) == (
        before["status"],
        before["enabled"],
    )
    for name in ("operation_id", "reason", "changed_at", "full_host_closure"):
        assert after["payload"][name] == before["payload"][name]
    async with case.engine.begin() as connection:
        await connection.run_sync(_migration, "downgrade")
        await connection.run_sync(_migration)
    assert await _authority(case) == after


@pytest.mark.asyncio
async def test_schema7_fails_closed_until_0063(realtime_gate_case):
    case = realtime_gate_case
    async with case.sessions() as session:
        with pytest.raises(HostMaintenanceUnavailable, match="does not cover"):
            await require_realtime_admission(session)
    async with case.engine.begin() as connection:
        await connection.run_sync(_migration)
    async with case.sessions() as session:
        snapshot = await require_realtime_admission(session)
        assert snapshot.schema_version == 8
        assert CONSUMER in snapshot.covered_scopes
        assert snapshot.full_host_closure is False


@pytest.mark.asyncio
async def test_shared_lock_blocks_close_until_producer_commit(realtime_gate_case):
    case = realtime_gate_case
    async with case.engine.begin() as connection:
        await connection.run_sync(_migration)
    before = await _authority(case)
    operation_id = str(uuid4())
    closer = None
    async with case.sessions() as producer:
        async with producer.begin():
            snapshot = await require_realtime_admission(producer)
            assert snapshot.is_open
            closer = asyncio.create_task(
                admission.close_admission(
                    operation_id=operation_id,
                    expected_generation=before["version"],
                    reason="isolated realtime maintenance close",
                    session_factory=case.sessions,
                )
            )
            await asyncio.sleep(0.15)
            assert not closer.done()
    assert closer is not None
    closed = await asyncio.wait_for(closer, 5)
    assert closed.status == "closed"
    assert closed.enabled is False
    assert closed.operation_id == operation_id


@pytest.mark.asyncio
async def test_closed_authority_blocks_helper_and_http_gate(realtime_gate_case):
    case = realtime_gate_case
    async with case.engine.begin() as connection:
        await connection.run_sync(_migration)
    before = await _authority(case)
    await admission.close_admission(
        operation_id=str(uuid4()),
        expected_generation=before["version"],
        reason="isolated realtime close",
        session_factory=case.sessions,
    )
    async with case.sessions() as session:
        with pytest.raises(HostMaintenanceClosed):
            await require_realtime_admission(session)
    async with case.sessions() as session:
        with pytest.raises(HTTPException) as error:
            await realtime_media._require_realtime_open(session)
        assert error.value.status_code == 503
        assert (
            error.value.detail
            == "Realtime media admission is temporarily closed for maintenance."
        )


@pytest.mark.asyncio
async def test_malformed_schema7_is_retained_not_reseeded(realtime_gate_case):
    case = realtime_gate_case
    async with case.sessions() as session:
        row = await session.get(OwnerControlRecord, case.authority_id)
        row.payload = {**row.payload, "scope": "invalid"}
        await session.commit()
    before = await _authority(case)
    async with case.engine.begin() as connection:
        await connection.run_sync(_migration)
    assert await _authority(case) == before
