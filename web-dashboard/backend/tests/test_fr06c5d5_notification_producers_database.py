"""Real PostgreSQL compatibility for business notification producers.

Dispatch maintenance must not roll back completed business transactions or drop
their in-app/outbox records. Every test owns a private schema in an explicitly
test-named database. No external message, provider job or filesystem work runs.
"""

from __future__ import annotations

import asyncio
import re
import subprocess
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, inspect, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.schema import CreateSchema, DropSchema

from app.api.owner import control_plane
from app.api.v1.endpoints import notifications
from app.core.auth import UserRecord, current_user
from app.core.config import settings
from app.db.base import Base, get_db
from app.db.models import (
    AIAgent,
    AIProvider,
    AuditEvent,
    CommunicationEndpoint,
    EscalationPolicy,
    HostMaintenanceWorkCycle,
    Job,
    Notification,
    NotificationDelivery,
    NotificationDeliveryAttempt,
    NotificationPreference,
    NotificationRule,
    Organization,
    OwnerControlRecord,
    Role,
    User,
)
from app.services import ai_runtime_service, communications
from app.services.host_maintenance_admission import (
    DOMAIN,
    HostMaintenanceClosed,
    NOTIFICATION_COVERAGE_SCOPE,
    NOTIFICATION_SCHEMA_VERSION,
    RESOURCE_ID,
    close_admission,
    open_admission,
)
from app.services.host_maintenance_notifications import (
    begin_notification_dispatch,
    mark_notification_activity_unresolved,
    register_notification_activity,
)

WAIT_SECONDS = 10


def _required_tables():
    tables = {
        model.__table__
        for model in (
            AIAgent,
            AIProvider,
            AuditEvent,
            CommunicationEndpoint,
            EscalationPolicy,
            HostMaintenanceWorkCycle,
            Job,
            Notification,
            NotificationDelivery,
            NotificationDeliveryAttempt,
            NotificationPreference,
            NotificationRule,
            Organization,
            OwnerControlRecord,
            Role,
            User,
        )
    }
    while True:
        expanded = tables | {
            key.column.table for table in tables for key in table.foreign_keys
        }
        if expanded == tables:
            return list(tables)
        tables = expanded


def _actor(user, organization, role, permissions):
    return UserRecord(
        id=user.id,
        email=user.email,
        name=user.name,
        role=role,
        password_hash=user.password_hash,
        organization_id=organization.id,
        organization_name=organization.name,
        organization_plan=organization.plan,
        permissions=permissions,
    )


@asynccontextmanager
async def isolated_notification_database(monkeypatch, *, allow_mock_whatsapp=False):
    """Reusable private PG context for the legacy owned WhatsApp regression too."""
    url = make_url(settings.DATABASE_URL)
    if url.drivername != "postgresql+asyncpg":
        pytest.skip("notification producer contracts require PostgreSQL/asyncpg")
    if re.search(
        r"(?:^|[_-])(test|pytest|ci|smoke|disposable)(?:$|[_-])",
        (url.database or "").lower(),
    ) is None:
        raise RuntimeError("notification producer tests require an isolated test database")

    schema = f"fr06c5d5_producer_{uuid4().hex}"
    administration = create_async_engine(url, poolclass=NullPool)
    engine = create_async_engine(
        url,
        poolclass=NullPool,
        connect_args={
            "server_settings": {"search_path": schema, "application_name": schema}
        },
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    case = SimpleNamespace(
        sessions=sessions,
        engine=engine,
        schema=schema,
        operation_id=str(uuid4()),
        worker_incarnation=str(uuid4()),
        requests=[],
        forbidden_attempts=[],
        realtime_ids=[],
    )
    created = False
    try:
        async with administration.begin() as connection:
            await connection.execute(CreateSchema(schema))
        created = True
        async with engine.begin() as connection:
            await connection.run_sync(
                lambda connection: Base.metadata.create_all(
                    connection, tables=_required_tables()
                )
            )
        async with sessions() as session:
            organizations = [
                Organization(
                    id=str(uuid4()),
                    name=name,
                    slug=f"isolated-notifications-{uuid4().hex}",
                    plan="enterprise",
                    status="active",
                )
                for name in ("Isolated Notification Organization", "Separate Organization")
            ]
            session.add_all(organizations)
            await session.flush()
            users = {}
            for label, role_name, organization in (
                ("Manager", "Manager", organizations[0]),
                ("Super Owner", "Super Owner", organizations[0]),
                ("Foreign", "Manager", organizations[1]),
            ):
                role = Role(
                    id=str(uuid4()), organization_id=organization.id,
                    name=role_name, status="active",
                )
                session.add(role)
                await session.flush()
                user = User(
                    id=str(uuid4()),
                    organization_id=organization.id,
                    role_id=role.id,
                    email=f"isolated-{uuid4().hex}@example.test",
                    name=f"Synthetic {label}",
                    password_hash="unused-synthetic-hash",
                    status="active",
                )
                session.add(user)
                users[label] = user
            await session.flush()
            session.add(
                OwnerControlRecord(
                    domain=DOMAIN,
                    resource_id=RESOURCE_ID,
                    status="open",
                    enabled=True,
                    version=4,
                    payload={
                        "schema_version": NOTIFICATION_SCHEMA_VERSION,
                        "scope": NOTIFICATION_COVERAGE_SCOPE,
                        "generation": 4,
                        "operation_id": case.operation_id,
                        "reason": "isolated-notification-producer-contract",
                        "changed_at": datetime.now(UTC).isoformat(),
                        "full_host_closure": False,
                    },
                )
            )
            session.add(
                NotificationRule(
                    id=str(uuid4()),
                    organization_id=organizations[0].id,
                    code=f"isolated-ai-completion-{uuid4().hex}",
                    name="Synthetic AI completion delivery",
                    event_pattern="ai.job.*",
                    audience="user",
                    channels=["in_app", "email"],
                    enabled=True,
                    system=False,
                )
            )
            await session.commit()
            case.organization = organizations[0]
            case.users = users
            case.actor = _actor(
                users["Manager"], organizations[0], "Manager",
                ["notifications:read", "notifications:write", "communications:read"],
            )
            case.owner = _actor(
                users["Super Owner"], organizations[0], "Super Owner", ["*"]
            )

        monkeypatch.setattr(settings, "SMTP_HOST", "smtp.synthetic.example.test")
        monkeypatch.setattr(settings, "SMTP_USER", None)
        monkeypatch.setattr(settings, "SMTP_PASSWORD", None)
        monkeypatch.setattr(settings, "SMTP_FROM_EMAIL", "synthetic@example.test")
        monkeypatch.setattr(settings, "FIREBASE_PROJECT_ID", None)
        monkeypatch.setattr(settings, "FIREBASE_ADMIN_CREDENTIALS_JSON", None)
        monkeypatch.setattr(
            settings, "AIOS_TELEGRAM_BOT_TOKEN_FILE",
            "/synthetic/unavailable/owner-telegram-token",
        )
        monkeypatch.setattr(
            settings, "AIOS_USER_TELEGRAM_BOT_TOKEN_FILE",
            "/synthetic/unavailable/user-telegram-token",
        )
        monkeypatch.setattr(settings, "AIOS_TELEGRAM_ALLOWED_USERS", [])
        monkeypatch.setattr(settings, "WHATSAPP_ACCESS_TOKEN", None)
        monkeypatch.setattr(settings, "WHATSAPP_PHONE_NUMBER_ID", None)
        monkeypatch.setattr(settings, "WHATSAPP_API_BASE", None)

        def forbidden_sync(*_args, **_kwargs):
            case.forbidden_attempts.append("runtime-io")
            raise AssertionError("notification producer tests must not perform runtime I/O")

        async def forbidden_async(*_args, **_kwargs):
            forbidden_sync()

        monkeypatch.setattr(communications, "_send_email", forbidden_sync)
        monkeypatch.setattr(communications, "_send_push", forbidden_sync)
        monkeypatch.setattr(communications, "_send_telegram", forbidden_async)
        if allow_mock_whatsapp:
            original_whatsapp = communications._send_whatsapp

            async def only_mock_whatsapp(address, notification, *, transport=None):
                assert isinstance(transport, httpx.MockTransport)
                return await original_whatsapp(
                    address, notification, transport=transport
                )

            monkeypatch.setattr(communications, "_send_whatsapp", only_mock_whatsapp)
        else:
            monkeypatch.setattr(communications, "_send_whatsapp", forbidden_async)
        monkeypatch.setattr(ai_runtime_service, "_execute_provider", forbidden_async)
        monkeypatch.setattr(ai_runtime_service, "SessionLocal", sessions)
        monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden_async)
        monkeypatch.setattr(asyncio, "create_subprocess_shell", forbidden_async)
        monkeypatch.setattr(subprocess, "Popen", forbidden_sync)
        for name in (
            "mkdir", "chmod", "unlink", "rename", "replace", "write_text", "write_bytes"
        ):
            monkeypatch.setattr(Path, name, forbidden_sync)

        async def publish_after_commit(notification):
            async with sessions() as observer:
                stored = await observer.get(Notification, notification.id)
                assert stored is not None
                assert stored.event_key == notification.event_key
            case.realtime_ids.append(notification.id)

        async def request_db():
            async with sessions() as session:
                case.requests.append(session)
                yield session

        async def actor_dependency():
            return case.actor

        monkeypatch.setattr(communications, "publish_realtime", publish_after_commit)
        app = FastAPI()
        app.include_router(notifications.router, prefix="/api/v1/notifications")
        app.include_router(control_plane.router, prefix="/api/v1")
        app.dependency_overrides[get_db] = request_db
        app.dependency_overrides[current_user] = actor_dependency
        case.app = app
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://isolated.test",
        ) as client:
            case.client = client
            yield case
    finally:
        await engine.dispose()
        if created:
            async with administration.begin() as connection:
                await connection.execute(DropSchema(schema, cascade=True))
        await administration.dispose()


@pytest_asyncio.fixture
async def producer_case(monkeypatch):
    async with isolated_notification_database(monkeypatch) as case:
        yield case


async def _close(case):
    return await close_admission(
        operation_id=case.operation_id,
        expected_generation=4,
        reason="isolated-notification-dispatch-close",
        session_factory=case.sessions,
    )


async def _reopen(case, closed):
    return await open_admission(
        operation_id=case.operation_id,
        expected_generation=closed.generation,
        reason="isolated-notification-dispatch-reopen",
        session_factory=case.sessions,
    )


async def _rows(case, model):
    async with case.sessions() as session:
        items = (await session.scalars(select(model).order_by(model.id))).all()
        return [
            {
                column.key: getattr(item, column.key)
                for column in inspect(model).column_attrs
            }
            for item in items
        ]


async def _notification(case, *, user=None, channels=None, key=None):
    async with case.sessions() as session:
        recipient = await session.get(User, (user or case.users["Manager"]).id)
        notification = await communications.create_notification(
            session,
            recipient,
            event_key="synthetic.producer.notification",
            category="system",
            title="Synthetic durable notification",
            message="Business completion and its delivery intent must survive dispatch closure.",
            severity="warning",
            channels=channels or ["in_app", "email"],
            dedupe_key=key,
            respect_preferences=False,
            actor_id=case.actor.id,
        )
        await session.commit()
        return notification.id


async def _delivery(case, notification_id, channel="email"):
    async with case.sessions() as session:
        item = await session.scalar(
            select(NotificationDelivery).where(
                NotificationDelivery.notification_id == notification_id,
                NotificationDelivery.channel == channel,
            )
        )
        assert item is not None
        return item


async def _assert_no_dispatch(case):
    assert await _rows(case, NotificationDeliveryAttempt) == []
    assert await _rows(case, HostMaintenanceWorkCycle) == []
    assert not case.forbidden_attempts


async def _claim(case):
    async with case.sessions() as session:
        return await communications.claim_due_deliveries(
            session, worker_incarnation=case.worker_incarnation, limit=1
        )


async def _assert_claim_closed(case):
    with pytest.raises(HostMaintenanceClosed):
        await _claim(case)


@pytest.mark.asyncio
async def test_closed_dispatch_preserves_real_notification_and_selected_external_channel(
    producer_case,
):
    case = producer_case
    await _close(case)
    notification_id = await _notification(case, key="closed-durable-notification")
    async with case.sessions() as observer:
        notification = await observer.get(Notification, notification_id)
        assert notification is not None
        deliveries = (
            await observer.scalars(
                select(NotificationDelivery).where(
                    NotificationDelivery.notification_id == notification_id
                )
            )
        ).all()
        assert {row.channel: row.status for row in deliveries} == {
            "in_app": "delivered", "email": "queued"
        }
        assert await observer.scalar(
            select(func.count()).select_from(AuditEvent).where(
                AuditEvent.action == "notification.created",
                AuditEvent.resource_id == notification_id,
            )
        ) == 1
    before = await _rows(case, NotificationDelivery)
    await _assert_claim_closed(case)
    assert await _rows(case, NotificationDelivery) == before
    await _assert_no_dispatch(case)


@pytest.mark.asyncio
async def test_closed_dispatch_dedupe_adds_new_channel_once_without_dropping_it(
    producer_case,
):
    case = producer_case
    first = await _notification(case, channels=["in_app"], key="closed-added-channel")
    await _close(case)
    second = await _notification(case, key="closed-added-channel")
    third = await _notification(case, key="closed-added-channel")
    assert first == second == third
    assert len(await _rows(case, Notification)) == 1
    deliveries = await _rows(case, NotificationDelivery)
    assert {row["channel"]: row["status"] for row in deliveries} == {
        "in_app": "delivered", "email": "queued"
    }
    async with case.sessions() as observer:
        assert await observer.scalar(
            select(func.count()).select_from(AuditEvent).where(
                AuditEvent.action == "notification.delivery.channels_reconciled",
                AuditEvent.resource_id == first,
            )
        ) == 1
    await _assert_no_dispatch(case)


@pytest.mark.asyncio
async def test_notification_create_api_retains_201_while_dispatch_is_closed(producer_case):
    case = producer_case
    await _close(case)
    response = await case.client.post(
        "/api/v1/notifications",
        json={
            "event_key": "synthetic.api.notification",
            "title": "API durable intent",
            "message": "Retain the in-app record and queued external delivery.",
            "channels": ["in_app", "email"],
            "dedupe_key": "closed-api-create",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert {row["channel"]: row["status"] for row in body["deliveries"]} == {
        "in_app": "delivered", "email": "queued"
    }
    assert case.realtime_ids == [body["id"]]
    assert len(await _rows(case, Notification)) == 1
    await _assert_claim_closed(case)
    await _assert_no_dispatch(case)


@pytest.mark.asyncio
@pytest.mark.parametrize("succeeded", [True, False], ids=["completed", "failed"])
async def test_actual_ai_job_completion_commits_notifications_after_dispatch_closes(
    producer_case, monkeypatch, succeeded
):
    case = producer_case
    provider_id, agent_id, job_id = (str(uuid4()) for _ in range(3))
    async with case.sessions() as session:
        session.add(
            AIProvider(
                id=provider_id,
                organization_id=case.organization.id,
                name="Synthetic completion provider",
                type="openai",
                status="configured",
                config={"enabled": True},
            )
        )
        await session.flush()
        session.add(
            AIAgent(
                id=agent_id,
                organization_id=case.organization.id,
                provider_id=provider_id,
                name="Synthetic completion agent",
                slug=f"completion-{agent_id}",
                role="Engineer",
                department="Engineering",
                model="synthetic-model",
                status="idle",
                metrics={},
            )
        )
        await session.flush()
        session.add(
            Job(
                id=job_id,
                organization_id=case.organization.id,
                agent_id=agent_id,
                type="ai_agent",
                status="queued",
                payload={
                    "prompt": "synthetic completion",
                    "requested_by_id": case.users["Manager"].id,
                },
            )
        )
        await session.commit()

    provider_entered = asyncio.Event()
    release_provider = asyncio.Event()

    async def synthetic_provider(provider, agent, prompt):
        assert provider.id == provider_id and agent.id == agent_id
        assert prompt == "synthetic completion"
        async with case.sessions() as observer:
            job = await observer.get(Job, job_id)
            assert job.status == "running" and job.started_at is not None
        provider_entered.set()
        await release_provider.wait()
        if not succeeded:
            raise RuntimeError("synthetic settled provider failure")
        return {
            "text": "synthetic completed result",
            "usage": {"input_tokens": 3, "output_tokens": 4, "total_tokens": 7},
            "cost": 0.0007,
            "latency_ms": 12.0,
        }

    monkeypatch.setattr(ai_runtime_service, "_execute_provider", synthetic_provider)
    task = asyncio.create_task(ai_runtime_service.run_job(job_id))
    try:
        await asyncio.wait_for(provider_entered.wait(), timeout=WAIT_SECONDS)
        await _close(case)
        release_provider.set()
        await asyncio.wait_for(task, timeout=WAIT_SECONDS)
    finally:
        release_provider.set()
        if not task.done():
            task.cancel()
        await asyncio.wait_for(
            asyncio.gather(task, return_exceptions=True), timeout=WAIT_SECONDS
        )

    expected = "completed" if succeeded else "failed"
    async with case.sessions() as observer:
        job = await observer.get(Job, job_id)
        agent = await observer.get(AIAgent, agent_id)
        provider = await observer.get(AIProvider, provider_id)
        assert job.status == expected and job.finished_at is not None
        if succeeded:
            assert job.result["text"] == "synthetic completed result"
            assert agent.metrics["tasks_completed"] == 1
            assert agent.metrics["tokens_used"] == 7
            assert provider.config["usage_today"] == 7
            assert provider.status == "connected"
        else:
            assert job.error == "Provider execution failed (RuntimeError)"
            assert agent.metrics["tasks_failed"] == 1
            assert provider.status == "error"
        assert await observer.scalar(
            select(func.count()).select_from(AuditEvent).where(
                AuditEvent.action == f"ai.job.{expected}",
                AuditEvent.resource_id == job_id,
            )
        ) == 1
        notification = await observer.scalar(
            select(Notification).where(Notification.source_id == job_id)
        )
        assert notification is not None
        assert notification.event_key == f"ai.job.{expected}"
        delivery_rows = (
            await observer.scalars(
                select(NotificationDelivery).where(
                    NotificationDelivery.notification_id == notification.id
                )
            )
        ).all()
        assert {row.channel: row.status for row in delivery_rows} == {
            "in_app": "delivered", "email": "queued"
        }
        assert case.realtime_ids == [notification.id]
    await _assert_claim_closed(case)
    await _assert_no_dispatch(case)


def _retry_path(case, delivery_id, route):
    if route == "owner":
        case.actor = case.owner
        return f"/api/v1/owner/communications/deliveries/{delivery_id}/retry"
    return f"/api/v1/notifications/deliveries/{delivery_id}/retry"


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["tenant", "owner"])
async def test_manual_retry_can_preserve_unstarted_backlog_while_dispatch_is_closed(
    producer_case, route
):
    case = producer_case
    notification_id = await _notification(case)
    delivery = await _delivery(case, notification_id)
    async with case.sessions() as session:
        item = await session.get(NotificationDelivery, delivery.id)
        item.status = "unconfigured"
        item.error_code = "provider_unconfigured"
        await session.commit()
    await _close(case)
    response = await case.client.post(_retry_path(case, delivery.id, route))
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "queued"
    await _assert_claim_closed(case)
    async with case.sessions() as observer:
        stored = await observer.get(NotificationDelivery, delivery.id)
        assert stored.status == "queued"
        assert await observer.scalar(
            select(func.count()).select_from(AuditEvent).where(
                AuditEvent.action == "notification.delivery.requeued",
                AuditEvent.resource_id == delivery.id,
            )
        ) == 1
    await _assert_no_dispatch(case)


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["tenant", "owner"])
async def test_manual_requeue_cannot_erase_unresolved_attempt_or_make_it_claimable(
    producer_case, route
):
    case = producer_case
    notification_id = await _notification(case)
    delivery = await _delivery(case, notification_id)
    async with case.sessions() as session:
        ownership = await register_notification_activity(
            session, delivery_id=delivery.id,
            worker_incarnation=case.worker_incarnation,
        )
        await session.commit()
    async with case.sessions() as session:
        await begin_notification_dispatch(session, ownership)
        await session.commit()
    await mark_notification_activity_unresolved(
        ownership,
        reason="synthetic-provider-outcome-unknown",
        session_factory=case.sessions,
    )
    # Model a mutable legacy/business row that an operator can requeue. The
    # independent committed attempt/activity must remain authoritative.
    async with case.sessions() as session:
        item = await session.get(NotificationDelivery, delivery.id)
        item.status = "dead_letter"
        item.dead_lettered_at = datetime.now(UTC)
        await session.commit()
    attempts_before = await _rows(case, NotificationDeliveryAttempt)
    activity_before = await _rows(case, HostMaintenanceWorkCycle)
    assert len(attempts_before) == len(activity_before) == 1
    assert activity_before[0]["state"] == "unresolved"
    closed = await _close(case)
    response = await case.client.post(_retry_path(case, delivery.id, route))
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "queued"
    assert await _rows(case, NotificationDeliveryAttempt) == attempts_before
    assert await _rows(case, HostMaintenanceWorkCycle) == activity_before
    await _assert_claim_closed(case)
    await _reopen(case, closed)
    assert await _claim(case) == []
    assert await _rows(case, NotificationDeliveryAttempt) == attempts_before
    assert await _rows(case, HostMaintenanceWorkCycle) == activity_before
    assert not case.forbidden_attempts


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["tenant", "owner"])
async def test_retry_permissions_remain_required_during_dispatch_closure(
    producer_case, route
):
    case = producer_case
    notification_id = await _notification(case)
    delivery = await _delivery(case, notification_id)
    await _close(case)
    path = _retry_path(case, delivery.id, route)
    case.actor = replace(case.actor, role="Member", permissions=[])
    before = await _rows(case, NotificationDelivery)
    response = await case.client.post(path)
    assert response.status_code == 403, response.text
    assert await _rows(case, NotificationDelivery) == before
    await _assert_no_dispatch(case)


@pytest.mark.asyncio
async def test_tenant_retry_keeps_foreign_delivery_hidden_during_dispatch_closure(
    producer_case,
):
    case = producer_case
    notification_id = await _notification(case, user=case.users["Foreign"])
    delivery = await _delivery(case, notification_id)
    await _close(case)
    before = await _rows(case, NotificationDelivery)
    response = await case.client.post(
        f"/api/v1/notifications/deliveries/{delivery.id}/retry"
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "Notification delivery not found"}
    assert await _rows(case, NotificationDelivery) == before
    await _assert_no_dispatch(case)
