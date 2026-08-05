"""Single-server project execution API, worker, migration, and safety contracts."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from starlette.requests import Request

from app.api.v1.router import api_router
from app.core.auth import UserRecord, current_user
from app.core.config import settings
from app.db.base import Base, SessionLocal
from app.db.models import (
    AuditEvent,
    Notification,
    Organization,
    Project,
    ProjectExecution,
    User,
    Workspace,
)
from app.services import free_tier
from app.services.project_execution import (
    ProjectExecutionConfigurationError,
    ProjectPlanningRunner,
    load_project_provider_secret,
)


ROOT = Path(__file__).resolve().parents[3]


def _actor(user_id: str, organization_id: str, organization_name: str) -> UserRecord:
    return UserRecord(
        id=user_id,
        email=f"{user_id}@example.com",
        name="Project Pilot Operator",
        role="Manager",
        password_hash="unused",
        organization_id=organization_id,
        organization_name=organization_name,
        organization_plan="enterprise",
        permissions=["projects:read", "projects:write"],
    )


async def _create_project_tenant(suffix: str):
    organization = Organization(
        id=f"pilot-org-{suffix}",
        name=f"Project Pilot {suffix}",
        slug=f"project-pilot-{suffix}",
        plan="enterprise",
        status="active",
    )
    user = User(
        id=f"pilot-user-{suffix}",
        organization_id=organization.id,
        role_id=None,
        email=f"pilot-{suffix}@example.com",
        name="Project Pilot Operator",
        password_hash="unused",
        status="active",
    )
    workspace = Workspace(
        id=f"pilot-workspace-{suffix}",
        organization_id=organization.id,
        name="Pilot Workspace",
        slug=f"pilot-workspace-{suffix}",
        status="active",
    )
    project = Project(
        id=f"pilot-project-{suffix}",
        organization_id=organization.id,
        workspace_id=workspace.id,
        owner_id=user.id,
        name="Real Single Server Pilot",
        slug=f"real-single-server-pilot-{suffix}",
        description=(
            "Design a bilingual social media campaign management product with "
            "secure accounts, project planning, analytics, and mobile delivery."
        ),
        status="planning",
        priority="high",
        progress=0,
        tags=["phase25", "pilot"],
    )
    async with SessionLocal() as session:
        session.add(organization)
        await session.flush()
        session.add_all([user, workspace])
        await session.flush()
        session.add(project)
        await session.commit()
    return organization, user, workspace, project


async def _cleanup(organization_id: str) -> None:
    async with SessionLocal() as session:
        await session.execute(
            delete(AuditEvent).where(AuditEvent.organization_id == organization_id)
        )
        await session.execute(
            delete(Notification).where(Notification.organization_id == organization_id)
        )
        await session.execute(
            delete(ProjectExecution).where(
                ProjectExecution.organization_id == organization_id
            )
        )
        await session.execute(delete(Project).where(Project.organization_id == organization_id))
        await session.execute(
            delete(Workspace).where(Workspace.organization_id == organization_id)
        )
        await session.execute(delete(User).where(User.organization_id == organization_id))
        await session.execute(delete(Organization).where(Organization.id == organization_id))
        await session.commit()


def test_project_execution_table_and_compose_worker_contracts() -> None:
    assert "project_executions" in Base.metadata.tables
    table = Base.metadata.tables["project_executions"]
    assert table.c.external_processing_confirmed.nullable is False
    assert table.c.budget_cap_usd.nullable is False
    assert any(
        index.name == "ix_project_executions_org_status_created"
        for index in table.indexes
    )

    compose = (ROOT / "web-dashboard/docker-compose.production.yml").read_text(
        encoding="utf-8"
    )
    assert 'profiles: ["ai-execution"]' in compose
    assert "app.services.project_execution_worker" in compose
    assert "/run/secrets/aionex/project-openai.env:ro" in compose
    assert "/run/references/phase22b/local-qwen3-8b:ro" in compose
    assert "project_execution_data:/var/lib/aionex/project-executions" in compose


@pytest.mark.asyncio
async def test_project_execution_api_requires_consent_is_durable_and_tenant_scoped() -> None:
    suffix = uuid4().hex[:12]
    organization, user, _, project = await _create_project_tenant(suffix)
    actor_holder = {"actor": _actor(user.id, organization.id, organization.name)}
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    app.dependency_overrides[current_user] = lambda: actor_holder["actor"]

    other_org_id = f"other-org-{suffix}"
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            denied = await client.post(
                f"/api/v1/projects/{project.id}/executions",
                json={"confirm_external_processing": False},
            )
            assert denied.status_code == 422, denied.text

            accepted = await client.post(
                f"/api/v1/projects/{project.id}/executions",
                json={"confirm_external_processing": True},
            )
            assert accepted.status_code == 202, accepted.text
            execution = accepted.json()
            assert execution["status"] == "queued"
            assert execution["provider"] == "openai"
            assert execution["budget_cap_usd"] <= 0.05
            assert execution["result"] is None
            assert "evidence_path" not in execution

            duplicate = await client.post(
                f"/api/v1/projects/{project.id}/executions",
                json={"confirm_external_processing": True},
            )
            assert duplicate.status_code == 409, duplicate.text

            listed = await client.get(
                f"/api/v1/projects/{project.id}/executions"
            )
            assert listed.status_code == 200, listed.text
            assert [item["id"] for item in listed.json()] == [execution["id"]]

            loaded = await client.get(
                f"/api/v1/projects/{project.id}/executions/{execution['id']}"
            )
            assert loaded.status_code == 200, loaded.text

            actor_holder["actor"] = _actor(
                "other-user", other_org_id, "Other Tenant"
            )
            isolated = await client.get(
                f"/api/v1/projects/{project.id}/executions/{execution['id']}"
            )
            assert isolated.status_code == 404
    finally:
        await _cleanup(organization.id)


@pytest.mark.asyncio
async def test_free_project_guard_only_counts_collection_creation(monkeypatch) -> None:
    actor = UserRecord(
        id="free-user",
        email="free@example.com",
        name="Free User",
        role=free_tier.FREE_USER_ROLE_NAME,
        password_hash="unused",
        organization_id="free-org",
        organization_name="Free Org",
        organization_plan=free_tier.FREE_PLAN_NAME,
        permissions=["projects:read", "projects:write"],
    )
    calls = []

    async def guarded(session, actor):
        calls.append(actor.id)

    monkeypatch.setattr(free_tier, "assert_free_project_creation_allowed", guarded)
    session = object()

    execution_request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/projects/project-1/executions",
            "headers": [],
        }
    )
    await free_tier.enforce_free_project_request(execution_request, actor, session)
    assert calls == []

    create_request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/projects",
            "headers": [],
        }
    )
    await free_tier.enforce_free_project_request(create_request, actor, session)
    assert calls == [actor.id]


def test_external_project_secret_is_strict_and_redacted(tmp_path) -> None:
    secret = tmp_path / "project-openai.env"
    secret.write_text(
        "OPENAI_API_KEY=test-provider-key-not-real\n"
        "AIOS_PHASE22C_MODEL=gpt-5-mini\n",
        encoding="utf-8",
    )
    secret.chmod(0o600)
    loaded = load_project_provider_secret(secret)
    assert loaded.model == "gpt-5-mini"
    assert "sk-proj" not in repr(loaded)

    secret.chmod(0o644)
    with pytest.raises(ProjectExecutionConfigurationError):
        load_project_provider_secret(secret)


def test_runner_recovers_completed_manifest_without_provider_call(tmp_path, monkeypatch) -> None:
    output_root = tmp_path / "output"
    local_reference = tmp_path / "local"
    local_reference.mkdir()
    (local_reference / "manifest.json").write_text("{}", encoding="utf-8")
    secret = tmp_path / "secret.env"
    secret.write_text(
        "OPENAI_API_KEY=test-provider-key-not-real\n"
        "AIOS_PHASE22C_MODEL=gpt-5-mini\n",
        encoding="utf-8",
    )
    secret.chmod(0o600)

    monkeypatch.setattr(settings, "PROJECT_EXECUTION_OUTPUT_ROOT", str(output_root))
    monkeypatch.setattr(settings, "PROJECT_EXECUTION_LOCAL_REFERENCE", str(local_reference))
    monkeypatch.setattr(settings, "PROJECT_EXECUTION_SECRET_FILE", str(secret))
    monkeypatch.setattr(settings, "PROJECT_EXECUTION_BUDGET_CAP_USD", 0.05)

    cloud = output_root / "job-1" / "cloud"
    cloud.mkdir(parents=True)
    (cloud / "comparison.json").write_text(
        json.dumps({"winner_by_quality": "openai"}), encoding="utf-8"
    )
    (cloud / "manifest.json").write_text(
        json.dumps(
            {
                "provider": "openai",
                "model": "gpt-5-mini",
                "execution_id": "cloud",
                "artifacts": [{"department": "Architecture"}],
                "requests_count": 6,
                "retries_count": 0,
                "input_tokens": 100,
                "output_tokens": 200,
                "total_tokens": 300,
                "calculated_cost": 0.000425,
                "budget_cap": 0.05,
                "total_duration": 2.0,
                "review": {
                    "approved": False,
                    "readiness_score": 0.82,
                    "blocking_findings": ["tests have not passed"],
                    "rework_plan": ["run tests"],
                },
            }
        ),
        encoding="utf-8",
    )

    result = ProjectPlanningRunner().run(
        job_id="job-1",
        project_name="Pilot Project",
        objective="Create a real controlled project plan without duplicate spending.",
    )
    assert result["success"] is True
    assert result["recovered_from_existing_evidence"] is True
    assert result["requests_count"] == 6
    assert (output_root / "job-1" / "execution-receipt.json").is_file()
