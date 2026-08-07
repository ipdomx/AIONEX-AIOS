"""Phase 29G operations, observability, security, recovery, and release contracts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select

from app.api.v1.router import api_router
from app.core.auth import UserRecord, current_user, pwd_context
from app.db.base import SessionLocal
from app.db.models import (
    Alert,
    AuditEvent,
    MetricSample,
    Organization,
    OwnerControlRecord,
    RefreshSession,
    Role,
    User,
)
from app.services import operations_assurance, operations_observer


class Identity:
    def __init__(self, organization: Organization, owner: User):
        self.organization = organization
        self.owner = owner

    def actor(self, permissions: list[str] | None = None) -> UserRecord:
        return UserRecord(
            id=self.owner.id,
            email=self.owner.email,
            name=self.owner.name,
            role="Super Owner",
            password_hash=self.owner.password_hash,
            organization_id=self.organization.id,
            organization_name=self.organization.name,
            organization_plan=self.organization.plan,
            permissions=permissions or ["*"],
        )


async def identity(suffix: str) -> Identity:
    organization = Organization(
        name=f"Phase 29G {suffix}",
        slug=f"phase29g-{suffix}",
        plan="enterprise",
        status="active",
    )
    async with SessionLocal() as session:
        session.add(organization)
        await session.flush()
        role = Role(
            organization_id=organization.id,
            name="Super Owner",
            system=True,
            status="active",
        )
        session.add(role)
        await session.flush()
        owner = User(
            organization_id=organization.id,
            role_id=role.id,
            email=f"phase29g-{suffix}@example.com",
            name=f"Phase 29G Owner {suffix}",
            password_hash=pwd_context.hash(f"Phase29G!{suffix}"),
            status="active",
        )
        session.add(owner)
        await session.commit()
    return Identity(organization, owner)


async def cleanup(organization_id: str) -> None:
    async with SessionLocal() as session:
        await session.execute(delete(Organization).where(Organization.id == organization_id))
        await session.commit()


def app_with_actor(holder: dict[str, UserRecord]) -> FastAPI:
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    app.dependency_overrides[current_user] = lambda: holder["actor"]
    return app


@pytest.mark.asyncio
async def test_live_inventory_is_truthful_and_observation_is_durable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def healthy_probe(host: str, port: int, timeout: float = 1.5):
        del host, port, timeout
        return True, 1.0

    async def healthy_redis():
        return {
            "id": "redis-primary",
            "name": "Redis",
            "type": "redis",
            "host": "redis",
            "port": 6379,
            "status": "connected",
            "size": 0.0,
            "connections": 1,
            "queries_per_second": 0,
            "slow_queries": 0,
            "backup_status": "not-applicable",
            "last_backup": None,
            "latency_ms": 1.0,
            "created_at": operations_assurance.iso(),
        }

    monkeypatch.setattr(operations_assurance, "tcp_probe", healthy_probe)
    monkeypatch.setattr(operations_assurance, "redis_snapshot", healthy_redis)

    async with SessionLocal() as session:
        inventory = await operations_assurance.service_inventory(session)
        ids = {item["id"] for item in inventory}
        assert {
            "backend",
            "frontend",
            "portal",
            "nginx-public",
            "nginx-owner",
            "nginx-portal",
            "postgres-primary",
            "redis-primary",
        } <= ids
        assert all(item["health"] == "healthy" for item in inventory)
        serialized = repr(inventory).lower()
        assert "container-0" not in serialized
        assert "prod-web-00" not in serialized
        assert "2024-01-01" not in serialized

        samples = await operations_assurance.record_observation_cycle(session)
        await session.commit()
        assert len(samples) >= 6
        assert all("status" in (sample.labels or {}) for sample in samples)
        assert (
            await session.scalar(
                select(func.count(MetricSample.id)).where(
                    MetricSample.name == "runtime.components.healthy"
                )
            )
            or 0
        ) >= 1
        observation = await session.scalar(
            select(AuditEvent)
            .where(AuditEvent.action == "operations.observation")
            .order_by(AuditEvent.created_at.desc())
        )
        assert observation is not None
        assert observation.details["status"] == "healthy"
        assert observation.details["trace_id"].startswith("obs-")


@pytest.mark.asyncio
async def test_security_event_session_revocation_traces_and_topology(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffix = uuid4().hex[:10]
    data = await identity(suffix)
    holder = {"actor": data.actor()}
    app = app_with_actor(holder)

    async def healthy_probe(host: str, port: int, timeout: float = 1.5):
        del host, port, timeout
        return True, 1.0

    async def healthy_redis():
        return {
            "id": "redis-primary",
            "name": "Redis",
            "type": "redis",
            "host": "redis",
            "port": 6379,
            "status": "connected",
            "size": 0.0,
            "connections": 1,
            "queries_per_second": 0,
            "slow_queries": 0,
            "backup_status": "not-applicable",
            "last_backup": None,
            "latency_ms": 1.0,
            "created_at": operations_assurance.iso(),
        }

    monkeypatch.setattr(operations_assurance, "tcp_probe", healthy_probe)
    monkeypatch.setattr(operations_assurance, "redis_snapshot", healthy_redis)

    try:
        async with SessionLocal() as session:
            refresh = RefreshSession(
                user_id=data.owner.id,
                token_hash=uuid4().hex + uuid4().hex,
                expires_at=datetime.now(UTC) + timedelta(days=1),
                ip_address="127.0.0.1",
                user_agent="phase29g-test",
            )
            session.add(refresh)
            await session.commit()
            refresh_id = refresh.id

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            event = await client.post(
                "/api/v1/security/events",
                params={
                    "event_type": "phase29g.validation",
                    "risk_score": 85,
                    "result": "detected",
                    "user_id": data.owner.id,
                    "ip": "127.0.0.1",
                },
            )
            assert event.status_code == 201, event.text
            assert event.json()["risk_level"] == "critical"

            events = await client.get("/api/v1/security/events")
            assert events.status_code == 200, events.text
            assert any(item["type"] == "phase29g.validation" for item in events.json())

            threats = await client.get("/api/v1/security/threats")
            assert threats.status_code == 200, threats.text
            assert any(item["severity"] == "critical" for item in threats.json())

            logged = await client.post(
                "/api/v1/monitoring/logs",
                params={
                    "level": "info",
                    "service": "phase29g",
                    "message": "trace evidence",
                    "trace_id": f"trace-{suffix}",
                },
            )
            assert logged.status_code == 200, logged.text
            traces = await client.get(
                "/api/v1/monitoring/traces",
                params={"trace_id": f"trace-{suffix}"},
            )
            assert traces.status_code == 200, traces.text
            assert traces.json()[0]["trace_id"] == f"trace-{suffix}"

            topology = await client.get("/api/v1/monitoring/topology")
            assert topology.status_code == 200, topology.text
            assert {item["id"] for item in topology.json()["nodes"]} >= {
                "backend",
                "postgres-primary",
                "redis-primary",
            }

            sessions = await client.get("/api/v1/security/sessions")
            assert sessions.status_code == 200, sessions.text
            assert any(item["id"] == refresh_id and item["active"] for item in sessions.json())
            revoked = await client.delete(f"/api/v1/security/sessions/{refresh_id}")
            assert revoked.status_code == 200, revoked.text

        async with SessionLocal() as session:
            stored = await session.get(RefreshSession, refresh_id)
            assert stored is not None and stored.revoked_at is not None
            security_audit = await session.scalar(
                select(AuditEvent).where(
                    AuditEvent.action == "security.session.revoked",
                    AuditEvent.resource_id == refresh_id,
                )
            )
            assert security_audit is not None
            critical = await session.scalar(
                select(Alert).where(
                    Alert.source == "security",
                    Alert.severity == "critical",
                )
            )
            assert critical is not None
    finally:
        await cleanup(data.organization.id)


@pytest.mark.asyncio
async def test_runtime_controls_fail_closed_and_maintenance_is_audited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffix = uuid4().hex[:10]
    data = await identity(suffix)
    holder = {"actor": data.actor()}
    app = app_with_actor(holder)

    async def inventory(_session):
        return [
            {
                "id": "backend",
                "name": "Backend API",
                "image": "runtime-managed",
                "status": "running",
                "server": "runtime-node",
                "cpu": 0.0,
                "memory": 0,
                "restart_count": None,
                "health": "healthy",
                "created_at": operations_assurance.iso(),
                "kind": "application",
                "endpoint": "backend:8000",
                "latency_ms": 1.0,
                "control_supported": False,
                "control_reason": "Direct Docker/host control is intentionally not delegated to the application container.",
            }
        ]

    monkeypatch.setattr(operations_assurance, "service_inventory", inventory)
    monkeypatch.setattr(
        operations_assurance,
        "host_snapshot",
        lambda: {
            "id": "runtime-node",
            "name": "runtime-node",
            "hostname": "runtime-node",
            "ip": None,
            "status": "online",
            "os": "Linux",
            "cpu_usage": 1.0,
            "memory_usage": 2.0,
            "disk_usage": 3.0,
            "network_rx": 0.0,
            "network_tx": 0.0,
            "uptime": 100,
            "location": "test",
            "provider": "self-managed",
            "load": {"1m": 0, "5m": 0, "15m": 0},
            "memory": {"total_bytes": 1, "used_bytes": 0},
            "disk": {"total_bytes": 1, "used_bytes": 0, "free_bytes": 1},
            "control_mode": "protected",
            "created_at": operations_assurance.iso(),
        },
    )

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            restart = await client.post("/api/v1/infrastructure/containers/backend/restart")
            assert restart.status_code == 409, restart.text
            assert restart.json()["detail"]["code"] == "DIRECT_RUNTIME_CONTROL_NOT_DELEGATED"

            reboot = await client.post("/api/v1/infrastructure/servers/runtime-node/reboot")
            assert reboot.status_code == 409, reboot.text

            maintenance = await client.post(
                "/api/v1/infrastructure/servers/runtime-node/maintenance",
                params={"enable": True},
            )
            assert maintenance.status_code == 200, maintenance.text
            assert maintenance.json()["maintenance"] is True

        async with SessionLocal() as session:
            denied = list(
                (
                    await session.scalars(
                        select(AuditEvent).where(
                            AuditEvent.organization_id == data.organization.id,
                            AuditEvent.action.in_(
                                {"runtime.control.denied", "server.reboot.denied"}
                            ),
                        )
                    )
                ).all()
            )
            assert {item.action for item in denied} == {
                "runtime.control.denied",
                "server.reboot.denied",
            }
            maintenance_record = await session.scalar(
                select(OwnerControlRecord).where(
                    OwnerControlRecord.domain == "runtime-maintenance",
                    OwnerControlRecord.resource_id == "runtime-node",
                )
            )
            assert maintenance_record is not None
            assert maintenance_record.enabled is True
    finally:
        await cleanup(data.organization.id)


@pytest.mark.asyncio
async def test_release_deployment_and_rollback_evidence_is_append_only() -> None:
    suffix = uuid4().hex[:10]
    data = await identity(suffix)
    holder = {"actor": data.actor()}
    app = app_with_actor(holder)
    commit = "0123456789abcdef0123456789abcdef01234567"
    digest = "sha256:" + "a" * 64
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            deployment = await client.post(
                "/api/v1/owner/releases/current-release/evidence",
                json={
                    "event": "deployment",
                    "commit": commit,
                    "image_digests": {"backend": digest},
                    "validated": True,
                    "note": "Phase 29G deployment validation",
                },
            )
            assert deployment.status_code == 201, deployment.text
            rollback = await client.post(
                "/api/v1/owner/releases/current-release/evidence",
                json={
                    "event": "rollback",
                    "commit": commit,
                    "image_digests": {"backend": digest},
                    "validated": True,
                    "note": "Phase 29G rollback drill",
                },
            )
            assert rollback.status_code == 201, rollback.text
            rejected = await client.post(
                "/api/v1/owner/releases/current-release/evidence",
                json={
                    "event": "deployment",
                    "commit": commit,
                    "image_digests": {},
                    "validated": False,
                },
            )
            assert rejected.status_code == 409
            releases = await client.get("/api/v1/owner/releases")
            assert releases.status_code == 200, releases.text
            candidate = releases.json()[0]
            assert candidate["deploymentEvidence"]["validated"] is True
            assert candidate["rollbackEvidence"]["validated"] is True

        async with SessionLocal() as session:
            count = int(
                await session.scalar(
                    select(func.count(AuditEvent.id)).where(
                        AuditEvent.organization_id == data.organization.id,
                        AuditEvent.action.in_({"release.deployment", "release.rollback"}),
                    )
                )
                or 0
            )
            assert count == 2
    finally:
        await cleanup(data.organization.id)


@pytest.mark.asyncio
async def test_operations_observer_initializes_and_closes_redis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    async def initialize() -> None:
        events.append("redis-initialized")

    async def close() -> None:
        events.append("redis-closed")

    async def run_forever(_observer: operations_observer.OperationsObserver) -> None:
        events.append("observer-ran")

    monkeypatch.setattr(operations_observer, "init_redis", initialize)
    monkeypatch.setattr(operations_observer, "close_redis", close)
    monkeypatch.setattr(
        operations_observer.OperationsObserver,
        "run_forever",
        run_forever,
    )

    assert await operations_observer.async_main() == 0
    assert events == ["redis-initialized", "observer-ran", "redis-closed"]


def test_phase29g_has_no_simulated_infrastructure_endpoints() -> None:
    root = Path(__file__).resolve().parents[3]
    for relative in (
        "web-dashboard/backend/app/api/v1/endpoints/containers.py",
        "web-dashboard/backend/app/api/v1/endpoints/databases.py",
        "web-dashboard/backend/app/api/v1/endpoints/servers.py",
        "web-dashboard/backend/app/api/v1/endpoints/security.py",
    ):
        source = (root / relative).read_text(encoding="utf-8").lower()
        assert "prod-web-00" not in source
        assert "container-{i}" not in source
        assert "2024-01-01t00:00:00z" not in source
        assert "implement as needed" not in source
        assert "this page is under development" not in source
