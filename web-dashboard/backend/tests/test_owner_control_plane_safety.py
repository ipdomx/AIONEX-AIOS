"""Safety and evidence contracts for the Owner control plane."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from starlette.requests import Request

from app.api.owner import control_plane
from app.api.v1.router import api_router
from app.core.auth import UserRecord, auth_service, current_user, pwd_context
from app.core.owner_policy import require_owner_service_allowed
import app.db.seed as seed_module
from app.db.base import SessionLocal
from app.db.models import (
    Organization,
    OwnerCommandRecord,
    OwnerControlRecord,
    Project,
    RefreshSession,
    Role,
    User,
    Workspace,
    uuid_str,
)
from app.db.seed import seed


def _test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    app.dependency_overrides[current_user] = lambda: UserRecord(
        id="owner-1",
        email="owner@aionex.local",
        name="AIONEX Owner",
        role="Super Owner",
        password_hash="unused",
        organization_id="aionex-org",
        organization_name="AIONEX Corp",
        organization_plan="enterprise",
        permissions=["*"],
    )
    return app


def _auth_request() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "headers": []})


def test_command_audit_redacts_nested_case_insensitive_secrets() -> None:
    payload = {
        "PASSWORD": "top-secret",
        "nested": [
            {
                "Api-Key": "provider-secret",
                "safe": "retained",
                "more": {"refresh_TOKEN": "session-secret"},
            }
        ],
    }

    assert control_plane._redact_sensitive(payload) == {
        "PASSWORD": "[REDACTED]",
        "nested": [
            {
                "Api-Key": "[REDACTED]",
                "safe": "retained",
                "more": {"refresh_TOKEN": "[REDACTED]"},
            }
        ],
    }

    command = OwnerCommandRecord(
        actor_id=None,
        domain="test",
        action="test",
        request={},
    )
    control_plane._finish_command(command, payload)
    serialized = json.dumps(command.result)
    assert "top-secret" not in serialized
    assert "provider-secret" not in serialized
    assert "session-secret" not in serialized
    assert command.result["nested"][0]["safe"] == "retained"


def test_repo_version_uses_configured_repository_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "VERSION").write_text("9.8.7\n", encoding="utf-8")
    monkeypatch.setenv("AIOS_REPO_ROOT", str(tmp_path))

    assert control_plane._repo_version() == "9.8.7"


@pytest.mark.asyncio
async def test_registered_organization_owner_never_receives_global_wildcard() -> None:
    await seed()
    suffix = uuid4().hex
    async with SessionLocal() as session:
        owner = await auth_service.register(
            session,
            email=f"organization-owner-{suffix}@example.com",
            password="OrganizationOwner!123",
            name="Organization Owner",
            organization_name=f"Organization {suffix}",
        )

    assert owner.role == "Owner"
    assert "*" not in owner.permissions
    assert "organizations:read" in owner.permissions
    assert "users:write" in owner.permissions


@pytest.mark.asyncio
async def test_bootstrap_password_reset_revokes_sessions_and_access_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await seed()
    suffix = uuid4().hex
    async with SessionLocal() as session:
        owner = await session.scalar(
            select(User).where(User.email == seed_module.OWNER_EMAIL)
        )
        assert owner is not None
        previous_auth_version = owner.auth_version
        refresh_session = RefreshSession(
            user_id=owner.id,
            token_hash=hashlib.sha256(f"bootstrap-reset-{suffix}".encode()).hexdigest(),
            expires_at=control_plane._now() + control_plane.timedelta(days=1),
        )
        session.add(refresh_session)
        await session.commit()
        refresh_session_id = refresh_session.id

    replacement = f"ReplacementOwner!{suffix}"
    monkeypatch.setattr(seed_module, "CONFIGURED_PASSWORD", replacement)
    monkeypatch.setattr(seed_module, "RESET_CONFIGURED_PASSWORD", True)
    monkeypatch.setattr(seed_module, "BOOTSTRAP_PASSWORD", replacement)
    await seed_module.seed()

    async with SessionLocal() as session:
        owner = await session.scalar(
            select(User).where(User.email == seed_module.OWNER_EMAIL)
        )
        refreshed = await session.get(RefreshSession, refresh_session_id)
        assert owner is not None
        assert refreshed is not None
        assert owner.auth_version == previous_auth_version + 1
        assert refreshed.revoked_at is not None
        assert pwd_context.verify(replacement, owner.password_hash)


@pytest.mark.asyncio
async def test_current_user_rejects_access_token_from_old_auth_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def decode(_token: str) -> dict[str, object]:
        return {"sub": "owner-1", "auth_version": 3}

    async def load_user(_session: object, _user_id: str) -> UserRecord:
        return UserRecord(
            id="owner-1",
            email="owner@example.com",
            name="Owner",
            role="Super Owner",
            password_hash="unused",
            organization_id="aionex-org",
            organization_name="AIONEX",
            organization_plan="enterprise",
            permissions=["*"],
            auth_version=4,
        )

    monkeypatch.setattr(auth_service, "decode_access_token", decode)
    monkeypatch.setattr(auth_service, "get_user_by_id", load_user)
    with pytest.raises(HTTPException) as stale:
        await current_user(
            request=_auth_request(),
            token="stale-token",
            session=object(),  # type: ignore[arg-type]
        )
    assert stale.value.status_code == 401


@pytest.mark.asyncio
async def test_finalization_requires_live_health_and_release_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def health(_session: object) -> list[dict[str, str]]:
        return [
            {
                "id": "database",
                "name": "PostgreSQL",
                "status": "healthy",
                "detail": "1 ms query latency",
            },
            {
                "id": "redis",
                "name": "Redis",
                "status": "healthy",
                "detail": "1 ms ping latency",
            },
        ]

    async def controls(
        _session: object,
        domain: str,
    ) -> list[dict[str, str]]:
        assert domain == "release"
        return [
            {
                "id": "security",
                "name": "Security Validation",
                "status": "passed",
                "lastResult": "No unresolved critical alerts",
            },
            {
                "id": "backup",
                "name": "Backup & Restore Verification",
                "status": "blocked",
                "lastResult": "No completed backup is available",
            },
        ]

    monkeypatch.setattr(control_plane, "_health_items", health)
    monkeypatch.setattr(control_plane, "_control_items", controls)
    monkeypatch.setattr(
        control_plane,
        "_revalidate_non_owner_release_gates",
        lambda session: controls(session, "release"),
    )

    snapshot = await control_plane.finalization(
        actor=UserRecord(
            id="owner-1",
            email="owner@aionex.local",
            name="AIONEX Owner",
            role="Super Owner",
            password_hash="unused",
            organization_id="aionex-org",
            organization_name="AIONEX Corp",
            organization_plan="enterprise",
            permissions=["*"],
        ),
        session=object(),  # type: ignore[arg-type]
    )

    assert snapshot["completion"] == 75
    checks = {item["id"]: item for item in snapshot["checks"]}
    assert checks["database"]["status"] == "passed"
    assert checks["release-security"]["status"] == "passed"
    assert checks["release-backup"]["status"] == "failed"
    assert checks["release-backup"]["category"] == "reliability"
    assert snapshot["program"]["current_batch"] == "29G"
    assert snapshot["program"]["models_providers_batch"] == "29J"
    assert snapshot["program"]["completion"] < 100


@pytest.mark.asyncio
async def test_finalization_recomputes_stale_release_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def health(_session: object) -> list[dict[str, str]]:
        return [
            {
                "id": "database",
                "name": "PostgreSQL",
                "status": "healthy",
                "detail": "live",
            }
        ]

    async def stored(
        _session: object,
        domain: str,
    ) -> list[dict[str, str]]:
        assert domain == "release"
        return [
            {
                "id": "security",
                "name": "Critical Incident Clearance",
                "status": "passed",
            },
            {
                "id": "approval",
                "name": "Final Owner Approval",
                "status": "passed",
            },
        ]

    async def live(_session: object) -> list[dict[str, str]]:
        return [
            {
                "id": "security",
                "name": "Critical Incident Clearance",
                "status": "blocked",
                "lastResult": "1 unresolved critical alert",
            }
        ]

    monkeypatch.setattr(control_plane, "_health_items", health)
    monkeypatch.setattr(control_plane, "_control_items", stored)
    monkeypatch.setattr(
        control_plane,
        "_revalidate_non_owner_release_gates",
        live,
    )

    snapshot = await control_plane.finalization(
        actor=_test_app().dependency_overrides[current_user](),
        session=object(),  # type: ignore[arg-type]
    )
    checks = {item["id"]: item for item in snapshot["checks"]}
    assert checks["release-security"]["status"] == "failed"
    assert snapshot["completion"] < 100
    assert snapshot["program"]["batches"][-1]["batch_id"] == "29J"
    assert snapshot["program"]["batches"][-1]["status"] == "deferred"


@pytest.mark.asyncio
async def test_default_seed_is_race_safe_across_workers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffix = uuid4().hex
    domain = f"race-{suffix[:20]}"
    resource_id = f"default-{suffix}"
    monkeypatch.setitem(
        control_plane.CONTROL_DEFAULTS,
        domain,
        [
            {
                "id": resource_id,
                "name": "Concurrent default",
                "status": "active",
                "enabled": True,
            }
        ],
    )

    async def initialize() -> None:
        async with SessionLocal() as session:
            await control_plane._ensure_defaults(session, domain)

    await asyncio.gather(*(initialize() for _ in range(8)))

    async with SessionLocal() as session:
        count = await session.scalar(
            select(func.count(OwnerControlRecord.id)).where(
                OwnerControlRecord.domain == domain,
                OwnerControlRecord.resource_id == resource_id,
            )
        )
    assert count == 1


@pytest.mark.asyncio
async def test_first_failed_mutation_never_leaves_an_accepted_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await seed()
    suffix = uuid4().hex
    domain = f"first-failure-{suffix[:16]}"
    resource_id = f"resource-{suffix}"
    monkeypatch.setitem(
        control_plane.CONTROL_DEFAULTS,
        domain,
        [
            {
                "id": resource_id,
                "name": "First-use default",
                "status": "active",
                "enabled": True,
            }
        ],
    )

    async def fail_after_default(
        _command: OwnerCommandRecord,
    ) -> dict[str, object]:
        await control_plane._control_record(active_session, domain, resource_id)
        raise HTTPException(status_code=409, detail="intentional first-use failure")

    async with SessionLocal() as active_session:
        with pytest.raises(HTTPException):
            await control_plane._run_audited_mutation(
                active_session,
                actor=_test_app().dependency_overrides[current_user](),
                domain=domain,
                resource_id=resource_id,
                action="validate",
                request={},
                mutation=fail_after_default,
            )

    async with SessionLocal() as session:
        commands = (
            await session.scalars(
                select(OwnerCommandRecord).where(
                    OwnerCommandRecord.domain == domain,
                    OwnerCommandRecord.resource_id == resource_id,
                )
            )
        ).all()
        assert len(commands) == 1
        assert commands[0].status == "failed"


@pytest.mark.asyncio
async def test_owner_service_policy_is_enforced_by_runtime_consumers() -> None:
    async with SessionLocal() as session:
        await control_plane._ensure_defaults(session, "services")
        service = await session.scalar(
            select(OwnerControlRecord)
            .where(
                OwnerControlRecord.domain == "services",
                OwnerControlRecord.resource_id == "openai",
            )
            .with_for_update()
        )
        assert service is not None
        service.enabled = False
        service.status = "paused"
        await session.commit()

    async with SessionLocal() as session:
        with pytest.raises(HTTPException) as blocked:
            await require_owner_service_allowed(session, "openai")
        assert blocked.value.status_code == 409

        service = await session.scalar(
            select(OwnerControlRecord)
            .where(
                OwnerControlRecord.domain == "services",
                OwnerControlRecord.resource_id == "openai",
            )
            .with_for_update()
        )
        assert service is not None
        service.enabled = True
        service.status = "active"
        await session.commit()

    async with SessionLocal() as session:
        await require_owner_service_allowed(session, "openai")


@pytest.mark.asyncio
async def test_system_map_reports_unavailable_metrics_instead_of_fake_zeroes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RedisProbe:
        async def ping(self) -> bool:
            return True

        async def info(self, section: str) -> dict[str, int]:
            assert section == "clients"
            return {"connected_clients": 7}

    async def redis_probe() -> RedisProbe:
        return RedisProbe()

    monkeypatch.setattr(control_plane, "get_redis", redis_probe)
    async with SessionLocal() as session:
        nodes = {
            node["id"]: node for node in await control_plane._system_map_items(session)
        }

    assert nodes["api-runtime"]["latency"] is None
    assert nodes["api-runtime"]["connections"] is None
    assert nodes["postgres-primary"]["load"] is None
    assert nodes["redis-primary"]["load"] is None
    assert nodes["redis-primary"]["connections"] == 7
    assert nodes["redis-primary"]["latency"] >= 1


@pytest.mark.asyncio
async def test_role_boundaries_and_failed_command_redaction() -> None:
    await seed()
    suffix = uuid4().hex
    org_a = Organization(
        id=uuid_str(),
        name=f"Tenant A {suffix}",
        slug=f"tenant-a-{suffix}",
        plan="enterprise",
        status="active",
    )
    org_b = Organization(
        id=uuid_str(),
        name=f"Tenant B {suffix}",
        slug=f"tenant-b-{suffix}",
        plan="enterprise",
        status="active",
    )
    role_a = Role(
        id=uuid_str(),
        organization_id=org_a.id,
        name=f"Operator A {suffix}",
        status="active",
    )
    local_owner_role = Role(
        id=uuid_str(),
        organization_id="aionex-org",
        name=f"Owner Tenant Operator {suffix}",
        status="active",
    )
    async with SessionLocal() as session:
        session.add_all([org_a, org_b])
        await session.flush()
        session.add_all([role_a, local_owner_role])
        await session.commit()

    app = _test_app()
    password = f"CrossTenant!{suffix}"
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        cross_tenant = await client.post(
            "/api/v1/owner/operations",
            json={
                "entity": "user",
                "operation": "create",
                "payload": {
                    "name": "Blocked User",
                    "email": f"blocked-{suffix}@example.com",
                    "password": password,
                    "role_id": role_a.id,
                    "organization_id": org_b.id,
                },
            },
        )
        assert cross_tenant.status_code == 409, cross_tenant.text

        super_owner_assignment = await client.post(
            "/api/v1/owner/operations",
            json={
                "entity": "user",
                "operation": "create",
                "payload": {
                    "name": "Blocked Owner",
                    "email": f"blocked-owner-{suffix}@example.com",
                    "password": f"ProtectedOwner!{suffix}",
                    "role_id": "super-owner-role",
                    "organization_id": "aionex-org",
                },
            },
        )
        assert super_owner_assignment.status_code == 409

        self_demotion = await client.post(
            "/api/v1/owner/operations",
            json={
                "entity": "user",
                "operation": "update",
                "id": "owner-1",
                "payload": {"role_id": local_owner_role.id},
            },
        )
        assert self_demotion.status_code == 409

    async with SessionLocal() as session:
        commands = (
            await session.scalars(
                select(OwnerCommandRecord)
                .where(
                    OwnerCommandRecord.domain == "operations",
                    OwnerCommandRecord.action == "user.create",
                    OwnerCommandRecord.status == "failed",
                )
                .order_by(OwnerCommandRecord.created_at.desc())
                .limit(2)
            )
        ).all()
        assert len(commands) == 2
        serialized = json.dumps([command.request for command in commands])
        assert password not in serialized
        assert f"ProtectedOwner!{suffix}" not in serialized
        assert all(
            command.request["payload"]["password"] == "[REDACTED]"
            for command in commands
        )


@pytest.mark.asyncio
async def test_suspension_revokes_refresh_and_pre_restore_access_sessions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await seed()
    suffix = uuid4().hex
    first_password = f"SessionOne!{suffix}"
    second_password = f"SessionTwo!{suffix}"
    organization = Organization(
        id=uuid_str(),
        name=f"Session Tenant {suffix}",
        slug=f"session-tenant-{suffix}",
        plan="enterprise",
        status="active",
    )
    role = Role(
        id=uuid_str(),
        organization_id=organization.id,
        name=f"Session Operator {suffix}",
        status="active",
    )
    user_one = User(
        id=uuid_str(),
        organization_id=organization.id,
        role_id=role.id,
        email=f"session-one-{suffix}@example.com",
        name="Session One",
        password_hash=pwd_context.hash(first_password),
        status="active",
    )
    user_two = User(
        id=uuid_str(),
        organization_id=organization.id,
        role_id=role.id,
        email=f"session-two-{suffix}@example.com",
        name="Session Two",
        password_hash=pwd_context.hash(second_password),
        status="active",
    )
    first_session = RefreshSession(
        id=uuid_str(),
        user_id=user_one.id,
        token_hash=hashlib.sha256(f"one-{suffix}".encode()).hexdigest(),
        expires_at=control_plane._now() + control_plane.timedelta(days=1),
    )
    second_session = RefreshSession(
        id=uuid_str(),
        user_id=user_two.id,
        token_hash=hashlib.sha256(f"two-{suffix}".encode()).hexdigest(),
        expires_at=control_plane._now() + control_plane.timedelta(days=1),
    )
    async with SessionLocal() as session:
        session.add(organization)
        await session.flush()
        session.add(role)
        await session.flush()
        session.add_all([user_one, user_two])
        await session.flush()
        session.add_all([first_session, second_session])
        await session.commit()

    async with SessionLocal() as session:
        first_record = await auth_service.authenticate(
            session,
            user_one.email,
            first_password,
        )
        second_record = await auth_service.authenticate(
            session,
            user_two.email,
            second_password,
        )
    first_access_token = auth_service.create_access_token(first_record)
    second_access_token = auth_service.create_access_token(second_record)

    app = _test_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        suspended_user = await client.post(
            "/api/v1/owner/operations",
            json={
                "entity": "user",
                "operation": "suspend",
                "id": user_one.id,
                "payload": {},
            },
        )
        assert suspended_user.status_code == 200, suspended_user.text

        suspended_organization = await client.post(
            "/api/v1/owner/operations",
            json={
                "entity": "organization",
                "operation": "suspend",
                "id": organization.id,
                "payload": {},
            },
        )
        assert suspended_organization.status_code == 200, suspended_organization.text

        restored_user = await client.post(
            "/api/v1/owner/operations",
            json={
                "entity": "user",
                "operation": "restore",
                "id": user_one.id,
                "payload": {},
            },
        )
        assert restored_user.status_code == 200, restored_user.text

        restored_organization = await client.post(
            "/api/v1/owner/operations",
            json={
                "entity": "organization",
                "operation": "restore",
                "id": organization.id,
                "payload": {},
            },
        )
        assert restored_organization.status_code == 200, restored_organization.text

        async with SessionLocal() as session:
            role_record = await auth_service.authenticate(
                session,
                user_two.email,
                second_password,
            )
        pre_role_suspend_token = auth_service.create_access_token(role_record)

        suspended_role = await client.post(
            f"/api/v1/owner/resources/access/{role.id}/actions",
            json={"action": "suspend", "payload": {}},
        )
        assert suspended_role.status_code == 200, suspended_role.text
        restored_role = await client.post(
            f"/api/v1/owner/resources/access/{role.id}/actions",
            json={"action": "restore", "payload": {}},
        )
        assert restored_role.status_code == 200, restored_role.text

    async with SessionLocal() as session:
        refreshed = (
            await session.scalars(
                select(RefreshSession).where(
                    RefreshSession.id.in_([first_session.id, second_session.id])
                )
            )
        ).all()
        assert len(refreshed) == 2
        assert all(item.revoked_at is not None for item in refreshed)
        refreshed_users = {
            item.id: item
            for item in (
                await session.scalars(
                    select(User).where(User.id.in_([user_one.id, user_two.id]))
                )
            ).all()
        }
        assert refreshed_users[user_one.id].auth_version == 3
        assert refreshed_users[user_two.id].auth_version == 2

        payloads = {
            token: auth_service._decode_access_token_payload(token)
            for token in (
                first_access_token,
                second_access_token,
                pre_role_suspend_token,
            )
        }

        async def decode_access_token(token: str) -> dict[str, object]:
            return payloads[token]

        monkeypatch.setattr(
            auth_service,
            "decode_access_token",
            decode_access_token,
        )
        for stale_token in payloads:
            with pytest.raises(HTTPException) as error:
                await current_user(
                    request=_auth_request(),
                    token=stale_token,
                    session=session,
                )
            assert error.value.status_code == 401
            assert error.value.detail == "Session is no longer valid"


@pytest.mark.asyncio
async def test_actions_return_evidence_and_protect_core_services(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await seed()
    suffix = uuid4().hex
    organization = Organization(
        id=uuid_str(),
        name=f"Project Tenant {suffix}",
        slug=f"project-tenant-{suffix}",
        status="active",
    )
    role = Role(
        id=uuid_str(),
        organization_id=organization.id,
        name=f"Project Owner {suffix}",
        status="active",
    )
    owner = User(
        id=uuid_str(),
        organization_id=organization.id,
        role_id=role.id,
        email=f"project-owner-{suffix}@example.com",
        name="Project Owner",
        password_hash=pwd_context.hash(f"ProjectOwner!{suffix}"),
        status="active",
    )
    workspace = Workspace(
        id=uuid_str(),
        organization_id=organization.id,
        name="Project Workspace",
        slug=f"project-workspace-{suffix}",
        status="active",
    )
    project = Project(
        id=uuid_str(),
        organization_id=organization.id,
        workspace_id=workspace.id,
        owner_id=owner.id,
        name="Validated Project",
        slug=f"validated-project-{suffix}",
        status="active",
        priority="medium",
    )
    async with SessionLocal() as session:
        session.add(organization)
        await session.flush()
        session.add_all([role, workspace])
        await session.flush()
        session.add(owner)
        await session.flush()
        session.add(project)
        await session.commit()

    healthy_evidence = [
        {
            "id": "database",
            "name": "PostgreSQL",
            "status": "healthy",
            "detail": "1 ms query latency",
        },
        {
            "id": "redis",
            "name": "Redis",
            "status": "healthy",
            "detail": "1 ms ping latency",
        },
    ]

    async def healthy(_session: object) -> list[dict[str, object]]:
        return healthy_evidence

    monkeypatch.setattr(control_plane, "_health_items", healthy)
    app = _test_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        validated = await client.post(
            f"/api/v1/owner/resources/projects/{project.id}/actions",
            json={"action": "validate", "payload": {}},
        )
        assert validated.status_code == 200, validated.text

        global_validation = await client.post(
            "/api/v1/owner/resources/global-command/all/actions",
            json={"action": "validate", "payload": {}},
        )
        assert global_validation.status_code == 200, global_validation.text

        vault_toggle = await client.post(
            "/api/v1/owner/resources/services/vault/actions",
            json={"action": "toggle", "payload": {}},
        )
        assert vault_toggle.status_code == 409, vault_toggle.text

        invalid_security_acknowledgement = await client.post(
            "/api/v1/owner/security-integration/secrets-vault/command",
            json={"action": "acknowledge"},
        )
        assert invalid_security_acknowledgement.status_code == 409
        assert (
            invalid_security_acknowledgement.json()["detail"]
            == "Only the threat-defense target can acknowledge alerts"
        )

        postgres_probe = await client.post(
            "/api/v1/owner/resources/integrations/postgres/actions",
            json={"action": "health-check", "payload": {}},
        )
        assert postgres_probe.status_code == 200, postgres_probe.text
        postgres = next(
            item for item in postgres_probe.json()["items"] if item["id"] == "postgres"
        )
        assert postgres["validationMode"] == "live"
        assert postgres["lastResult"]["status"] == "healthy"

    async with SessionLocal() as session:
        commands = (
            await session.scalars(
                select(OwnerCommandRecord)
                .where(
                    OwnerCommandRecord.actor_id == "owner-1",
                    OwnerCommandRecord.created_at
                    >= control_plane._now() - control_plane.timedelta(minutes=5),
                )
                .order_by(OwnerCommandRecord.created_at.desc())
            )
        ).all()
        global_command = next(
            item
            for item in commands
            if item.domain == "global-command" and item.action == "validate"
        )
        assert global_command.status == "completed"
        assert global_command.result["evidence"] == healthy_evidence
        vault_command = next(
            item
            for item in commands
            if item.domain == "services"
            and item.resource_id == "vault"
            and item.action == "toggle"
        )
        assert vault_command.status == "failed"
