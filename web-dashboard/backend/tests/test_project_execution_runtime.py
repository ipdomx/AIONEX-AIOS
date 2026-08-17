"""Project execution API, worker, migration, and safety contracts."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4
import zipfile

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from starlette.requests import Request

from app.api.v1.router import api_router
from app.api.v1.endpoints.project_executions import ProjectExecutionStart, start_project_execution
from app.core.auth import UserRecord, current_user
from app.core.config import settings
from app.db.base import Base, SessionLocal
from app.db.models import (
    AuditEvent,
    Notification,
    Organization,
    OwnerControlRecord,
    Project,
    ProjectExecution,
    User,
    Workspace,
)
from app.services import free_tier
from aios.cloud_provider_sandbox import OpenAITransportError
from app.services.project_execution import (
    ProjectExecutionConfigurationError,
    ProjectPlanningRunner,
    load_project_provider_secret,
    sanitized_execution_error,
)


ROOT = Path(__file__).resolve().parents[3]


def _actor(
    user_id: str,
    organization_id: str,
    organization_name: str,
    *,
    role: str = "Manager",
) -> UserRecord:
    return UserRecord(
        id=user_id,
        email=f"{user_id}@example.com",
        name="Project Pilot Operator",
        role=role,
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
        await session.execute(
            delete(OwnerControlRecord).where(
                OwnerControlRecord.domain == "digital-workforce",
                OwnerControlRecord.resource_id.like(f"{organization_id}:%"),
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
    assert "project_execution_data:/var/lib/aionex/project-executions:rw" in compose
    assert 'PROJECT_EXECUTION_LEGACY_MODEL: "gpt-5.6-luna"' in compose
    assert 'PROJECT_EXECUTION_RESEARCH_MODEL: "gpt-5.6-luna"' in compose
    assert "gpt-5.4-nano" not in compose

    worker_requirements = (
        ROOT / "web-dashboard/backend/requirements-project-worker.txt"
    ).read_text(encoding="utf-8")
    dockerfile = (ROOT / "web-dashboard/backend/Dockerfile").read_text(encoding="utf-8")
    assert "selenium==4.46.0" in worker_requirements
    assert "pip check" in dockerfile


@pytest.mark.asyncio
async def test_project_execution_api_requires_consent_is_durable_and_tenant_scoped(
    tmp_path: Path,
) -> None:
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
            assert execution["mode"] == "full"
            assert execution["budget_cap_usd"] <= 0.05
            assert execution["result"] is None
            assert "evidence_path" not in execution

            duplicate = await client.post(
                f"/api/v1/projects/{project.id}/executions",
                json={"confirm_external_processing": True},
            )
            assert duplicate.status_code == 409, duplicate.text

            evidence = tmp_path / "completed-cycle"
            package = evidence / "delivery-package"
            package.mkdir(parents=True)
            (package / "README.md").write_text(
                "governed delivery", encoding="utf-8"
            )
            async with SessionLocal() as session:
                completed = await session.get(ProjectExecution, execution["id"])
                assert completed is not None
                completed.status = "completed"
                completed.stage = "rework_required"
                completed.progress = 100
                completed.evidence_path = str(evidence)
                completed.result_summary = {
                    "success": True,
                    "phase": 28,
                    "mode": "full",
                    "status": "rework_required",
                    "approved": False,
                    "readiness_score": 0.82,
                    "blocking_findings": ["evidence required"],
                    "rework_plan": ["complete evidence"],
                    "workforce": [],
                    "requests_count": 8,
                    "retries_count": 0,
                    "input_tokens": 1,
                    "output_tokens": 1,
                    "total_tokens": 2,
                    "calculated_cost": 0.001,
                    "budget_cap": 0.05,
                    "total_duration": 1.0,
                    "provider": "openai",
                    "fallback_used": False,
                    "production_modified": False,
                }
                await session.commit()

            download = await client.get(
                f"/api/v1/projects/{project.id}/executions/{execution['id']}/download"
            )
            assert download.status_code == 200, download.text
            assert download.headers["content-type"] == "application/zip"
            assert download.content.startswith(b"PK")

            next_cycle = await client.post(
                f"/api/v1/projects/{project.id}/executions",
                json={"confirm_external_processing": True, "mode": "full"},
            )
            assert next_cycle.status_code == 202, next_cycle.text
            assert next_cycle.json()["id"] != execution["id"]

            listed = await client.get(
                f"/api/v1/projects/{project.id}/executions"
            )
            assert listed.status_code == 200, listed.text
            assert [item["id"] for item in listed.json()] == [
                next_cycle.json()["id"],
                execution["id"],
            ]

            loaded = await client.get(
                f"/api/v1/projects/{project.id}/executions/{execution['id']}"
            )
            assert loaded.status_code == 200, loaded.text
            assert loaded.json()["result"]["phase"] == 28

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
async def test_free_project_execution_fails_closed_until_local_phase36c_runtime_is_armed(
    monkeypatch,
) -> None:
    actor = UserRecord(
        id="free-project-ai-user",
        email="free-project-ai@example.com",
        name="Free Project AI User",
        role=free_tier.FREE_USER_ROLE_NAME,
        password_hash="unused",
        organization_id="free-project-ai-org",
        organization_name="Free Project AI Org",
        organization_plan=free_tier.FREE_PLAN_NAME,
        permissions=["projects:read", "projects:write"],
    )
    monkeypatch.setattr(settings, "PROJECT_EXECUTION_RUNNER_MODE", "legacy")
    monkeypatch.setattr(settings, "PROJECT_AI_LIVE_RUNTIME_ENABLED", False)

    with pytest.raises(HTTPException) as exc_info:
        await start_project_execution(
            "not-read-before-guard",
            ProjectExecutionStart(confirm_external_processing=True),
            actor=actor,
            _admission=None,
            session=object(),  # type: ignore[arg-type]
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["code"] == "FREE_PROJECT_AI_REQUIRES_LIVE_LOCAL_RUNTIME"


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
        "AIOS_PHASE22C_MODEL=gpt-5.6-luna\n",
        encoding="utf-8",
    )
    secret.chmod(0o600)
    loaded = load_project_provider_secret(secret)
    assert loaded.model == "gpt-5.6-luna"
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
        "OPENAI_API_KEY=[REDACTED]\n"
        "AIOS_PHASE22C_MODEL=gpt-5-mini\n",
        encoding="utf-8",
    )
    secret.chmod(0o600)

    monkeypatch.setattr(settings, "PROJECT_EXECUTION_OUTPUT_ROOT", str(output_root))
    monkeypatch.setattr(settings, "PROJECT_EXECUTION_LOCAL_REFERENCE", str(local_reference))
    monkeypatch.setattr(settings, "PROJECT_EXECUTION_SECRET_FILE", str(secret))
    monkeypatch.setattr(settings, "PROJECT_EXECUTION_BUDGET_CAP_USD", 0.05)

    job_root = output_root / "job-1"
    cloud = job_root / "cloud"
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
    full = job_root / "full-cycle" / "cycle"
    full.mkdir(parents=True)
    (full / "manifest.json").write_text(
        json.dumps(
            {
                "phase": 28,
                "mode": "full-governed-project-cycle",
                "execution_id": "cycle",
                "summary": {
                    "status": "rework_required",
                    "approved": False,
                    "readiness_score": 0.82,
                    "duration_seconds": 0.5,
                },
                "release_review": {
                    "blocking_findings": ["executed evidence required"],
                    "rework_plan": ["execute tests"],
                },
                "source_planning": {"model": "gpt-5-mini"},
                "external_research": {
                    "request_count": 1,
                    "search_calls": 1,
                    "input_tokens": 600,
                    "output_tokens": 400,
                    "total_tokens": 1000,
                    "calculated_cost": 0.01095,
                    "total_duration": 1.0,
                },
                "implementation": {
                    "requests_count": 1,
                    "input_tokens": 50,
                    "output_tokens": 60,
                    "total_tokens": 110,
                    "calculated_cost": 0.0001325,
                    "total_duration": 0.3,
                },
                "workforce": [],
                "proof": {"all_governance_layers_executed": True},
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
    assert result["requests_count"] == 8
    assert result["total_tokens"] == 1410
    assert result["all_governance_layers_executed"] is True
    assert (output_root / "job-1" / "execution-receipt.json").is_file()


@pytest.mark.asyncio
async def test_worker_persists_full_cycle_stages_and_digital_workforce() -> None:
    from sqlalchemy import select

    from app.services.project_execution_worker import ProjectExecutionWorker

    suffix = uuid4().hex[:12]
    organization, user, workspace, project = await _create_project_tenant(suffix)

    class FakeFullCycleRunner:
        def run(self, **payload):
            callback = payload["stage_callback"]
            callback("cognitive_review", 12)
            callback("workforce_execution", 64)
            callback("release_review", 96)
            return {
                "success": True,
                "phase": 28,
                "mode": "full",
                "status": "rework_required",
                "provider": "openai",
                "model": "gpt-5-mini",
                "output_directory": "/tmp/aionex-test-evidence",
                "requests_count": 8,
                "retries_count": 0,
                "input_tokens": 500,
                "output_tokens": 700,
                "total_tokens": 1200,
                "calculated_cost": 0.002,
                "budget_cap": 0.05,
                "total_duration": 3.0,
                "approved": False,
                "readiness_score": 0.82,
                "blocking_findings": ["executed security evidence required"],
                "rework_plan": ["complete security review"],
                "all_governance_layers_executed": True,
                "fallback_used": False,
                "production_modified": False,
                "workforce": [
                    {
                        "worker_id": "backend-specialist",
                        "role": "Backend Specialist",
                        "department": "Backend",
                        "ministry_id": "engineering",
                        "employment_state": "supervised",
                        "assignment_state": "rework",
                        "success_count": 0,
                        "failure_count": 1,
                        "quality": 82.0,
                        "operational_health": 92.0,
                        "trust": 90.0,
                        "learning": 86.0,
                        "recommendation": "Supervised rework",
                        "restrictions": ["supervised execution"],
                        "warnings": ["evidence required"],
                        "certifications": ["backend-evidence-recertification"],
                        "training": {
                            "course_id": "backend-evidence-recertification",
                            "score": 82.0,
                            "passed": True,
                        },
                    }
                ],
            }

    try:
        async with SessionLocal() as session:
            execution = ProjectExecution(
                organization_id=organization.id,
                workspace_id=workspace.id,
                project_id=project.id,
                requested_by_id=user.id,
                mode="full",
                provider="openai",
                status="queued",
                stage="queued",
                progress=0,
                objective=project.description or project.name,
                external_processing_confirmed=True,
                budget_cap_usd=0.05,
                result_summary={},
                attempts=0,
                max_attempts=1,
            )
            session.add(execution)
            await session.commit()
            execution_id = execution.id

        worker = ProjectExecutionWorker(runner=FakeFullCycleRunner())
        assert await worker.run_once() is True

        async with SessionLocal() as session:
            completed = await session.get(ProjectExecution, execution_id)
            assert completed is not None
            assert completed.status == "completed"
            assert completed.stage == "rework_required"
            assert completed.progress == 100
            assert completed.requests_count == 8
            assert completed.result_summary["phase"] == 28

            workforce = await session.scalar(
                select(OwnerControlRecord).where(
                    OwnerControlRecord.domain == "digital-workforce",
                    OwnerControlRecord.resource_id
                    == f"{organization.id}:backend-specialist",
                )
            )
            assert workforce is not None
            assert workforce.status == "supervised"
            assert workforce.payload["training"]["passed"] is True
            assert workforce.payload["execution_id"] == execution_id

            from app.api.owner import control_plane

            staff = await control_plane._staff_items(session)
            digital = [
                item
                for item in staff
                if item["kind"] == "digital"
                and item["name"] == "backend-specialist"
            ]
            assert len(digital) == 1
            assert digital[0]["performance"] == 82.0
            assert digital[0]["training"]["passed"] is True

            notification = await session.scalar(
                select(Notification).where(
                    Notification.organization_id == organization.id,
                    Notification.type == "project.execution.completed",
                )
            )
            assert notification is not None
            assert "cognitive" in notification.message

            updated_project = await session.get(Project, project.id)
            assert updated_project is not None
            assert updated_project.status == "planning"
            assert updated_project.progress >= 64
    finally:
        await _cleanup(organization.id)


def test_runner_executes_planning_prototype_and_full_governance_without_network(
    tmp_path, monkeypatch
) -> None:
    import hashlib
    from types import SimpleNamespace

    import app.services.project_execution as project_execution_module
    from aios.organization import EngineeringOrganization

    output_root = tmp_path / "output"
    local_reference = tmp_path / "local"
    local_reference.mkdir()
    (local_reference / "manifest.json").write_text("{}", encoding="utf-8")
    secret = tmp_path / "secret.env"
    secret.write_text(
        "OPENAI_API_KEY=[REDACTED]\n"
        "AIOS_PHASE22C_MODEL=gpt-5.6-luna\n",
        encoding="utf-8",
    )
    secret.chmod(0o600)

    monkeypatch.setattr(settings, "PROJECT_EXECUTION_OUTPUT_ROOT", str(output_root))
    monkeypatch.setattr(
        settings, "PROJECT_EXECUTION_LOCAL_REFERENCE", str(local_reference)
    )
    monkeypatch.setattr(settings, "PROJECT_EXECUTION_SECRET_FILE", str(secret))
    monkeypatch.setattr(settings, "PROJECT_EXECUTION_BUDGET_CAP_USD", 0.05)

    specification = {
        "schema_version": 3,
        "application_type": "web_application",
        "title": "Governed Project Workspace",
        "tagline": "A transparent workflow for controlled project delivery.",
        "summary": (
            "This functional prototype organizes the objective, workflow and "
            "retained evidence without claiming production deployment."
        ),
        "audience": "Project owners, reviewers and implementation teams",
        "features": [
            "Structured project overview",
            "Visible governed workflow",
            "Evidence and release boundaries",
        ],
        "brand": {
            "primary": "#E11D48",
            "secondary": "#0EA5E9",
            "accent": "#F8FAFC",
            "surface": "#050816",
            "logo_concept": "A geometric governed project mark",
        },
        "architecture": {
            "frontend": "Responsive browser interface",
            "backend": "Local Python application API",
            "data": "SQLite persistence",
            "realtime": "No realtime runtime requested",
            "deployment": "Local governed delivery package only",
        },
        "domain_blueprint": {
            "roles": ["member", "operator"],
            "entities": [
                {
                    "name": "project_record",
                    "label": "Project record",
                    "fields": [
                        {"name": "title", "type": "string", "required": True},
                        {"name": "notes", "type": "text", "required": False},
                        {"name": "active", "type": "boolean", "required": True},
                    ],
                }
            ],
            "workflows": [
                {
                    "name": "Create project record",
                    "trigger": "member submits a valid record",
                    "steps": ["validate input", "persist record", "return governed result"],
                }
            ],
        },
        "sections": [
            {
                "id": "overview",
                "title": "Project overview",
                "body": "Understand the requested outcome and intended audience.",
                "items": ["Objective summary", "Audience and value"],
            },
            {
                "id": "workflow",
                "title": "Governed workflow",
                "body": "Follow controlled stages from intake through review.",
                "items": ["Council review", "Engineering delivery"],
            },
            {
                "id": "evidence",
                "title": "Evidence boundary",
                "body": "Inspect proven evidence and explicit release limits.",
                "items": ["Retained hashes", "Verified rollback archive"],
            },
        ],
        "primary_action": "Review workflow",
        "secondary_action": "Inspect evidence",
        "limitations": ["No production deployment is claimed."],
    }

    class FakeOfficialTransport:
        def __init__(self, api_key, **kwargs):
            assert api_key
            self.model = "gpt-5.6-luna"

        async def validate_model(self, model):
            return {"id": model, "object": "model", "owned_by": "test"}

        async def __call__(self, payload):
            return {
                "text": json.dumps(specification),
                "usage": {
                    "input_tokens": 300,
                    "output_tokens": 500,
                    "total_tokens": 800,
                },
                "latency_ms": 100.0,
                "cost": 0.001075,
                "confidence": 1.0,
                "status": "completed",
                "actual_model": self.model,
                "reported_cost": None,
                "calculated_cost": 0.001075,
            }

    class FakeResearchResult:
        def sanitized(self):
            first = "https://standards.example.org/current"
            second = "https://guidance.example.net/latest"
            return {
                "provider": "openai",
                "model": "gpt-5.6-luna",
                "research_question": "Which current constraints affect the project?",
                "summary": "Independent current evidence supports controlled delivery.",
                "verified_facts": [
                    {
                        "claim": "The current standard requires retained evidence.",
                        "source_urls": [first],
                        "confidence": 0.94,
                    },
                    {
                        "claim": "The current guidance requires a release review.",
                        "source_urls": [second],
                        "confidence": 0.91,
                    },
                ],
                "risks": ["External requirements can change."],
                "unknowns": ["The final deployment jurisdiction is not selected."],
                "recommended_constraints": [
                    "Repeat research before production release."
                ],
                "sources": [
                    {
                        "url": first,
                        "title": "Current standard",
                        "domain": "standards.example.org",
                    },
                    {
                        "url": second,
                        "title": "Current guidance",
                        "domain": "guidance.example.net",
                    },
                ],
                "input_tokens": 600,
                "output_tokens": 400,
                "total_tokens": 1000,
                "calculated_cost": 0.01095,
                "tool_cost": 0.01,
                "total_duration": 1.0,
                "search_calls": 1,
                "raw_prompt_stored": False,
                "raw_response_stored": False,
                "authorization_header_stored": False,
                "fallback_used": False,
                "production_modified": False,
            }

    class FakeControlledResearch:
        def __init__(self, *args, **kwargs):
            pass

        def execute(self, **kwargs):
            return FakeResearchResult()

    class FakeCloudSandbox:
        def __init__(self, *args, **kwargs):
            pass

        def execute(
            self,
            *,
            execution_id,
            project,
            objective,
            output_root,
            **kwargs,
        ):
            destination = Path(output_root) / execution_id
            artifacts_dir = destination / "artifacts"
            artifacts_dir.mkdir(parents=True)
            blueprint = EngineeringOrganization().plan(project, objective)
            records = []
            for deliverable in blueprint.deliverables:
                model_output = {
                    "schema_version": 1,
                    "department": deliverable.department,
                    "summary": f"Validated {deliverable.department} plan.",
                    "implementation_plan": [
                        f"Implement {deliverable.department} boundaries.",
                        f"Verify {deliverable.department} evidence.",
                    ],
                    "technical_evidence": [
                        {
                            "criterion": criterion,
                            "evidence": f"Evidence for {criterion}.",
                            "verification": f"Verify {criterion} deterministically.",
                        }
                        for criterion in deliverable.acceptance_criteria
                    ],
                    "risks": [
                        {
                            "risk": f"{deliverable.department} regression",
                            "mitigation": "Retain rollback evidence and re-run tests.",
                        }
                    ],
                    "tests_passed": False,
                    "security_reviewed": False,
                }
                wrapper = {
                    "schema_version": 1,
                    "execution_id": execution_id,
                    "project": project,
                    "objective": objective,
                    "provider": "openai",
                    "model": "gpt-5.6-luna",
                    "department": deliverable.department,
                    "model_output": model_output,
                    "schema_valid": True,
                    "acceptance_coverage": 1.0,
                    "attempts": 1,
                    "attempt_errors": [],
                    "metrics": {},
                }
                path = artifacts_dir / f"{deliverable.department.lower()}.json"
                path.write_text(json.dumps(wrapper), encoding="utf-8")
                records.append(
                    {
                        "department": deliverable.department,
                        "path": f"artifacts/{path.name}",
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        "schema_valid": True,
                        "acceptance_coverage": 1.0,
                        "attempts": 1,
                        "errors": [],
                        "metrics": {},
                    }
                )
            manifest = {
                "schema_version": 1,
                "provider": "openai",
                "model": "gpt-5.6-luna",
                "execution_id": execution_id,
                "fallback_used": False,
                "production_modified": False,
                "artifacts": records,
                "requests_count": 6,
                "retries_count": 0,
                "input_tokens": 600,
                "output_tokens": 900,
                "total_tokens": 1500,
                "calculated_cost": 0.00195,
                "budget_cap": 0.05,
                "total_duration": 1.0,
                "review": {
                    "approved": False,
                    "readiness_score": 0.82,
                    "blocking_findings": ["tests have not passed"],
                    "rework_plan": ["execute tests"],
                },
            }
            manifest_path = destination / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            return SimpleNamespace(manifest_path=manifest_path)

    monkeypatch.setattr(
        project_execution_module,
        "load_project_provider_secret",
        lambda _path: project_execution_module.ProjectProviderSecret(
            api_key="test-key-not-a-secret", model="gpt-5.6-luna"
        ),
    )
    monkeypatch.setattr(
        project_execution_module,
        "OpenAIOfficialHTTPTransport",
        FakeOfficialTransport,
    )
    monkeypatch.setattr(
        project_execution_module,
        "ControlledWebResearch",
        FakeControlledResearch,
    )
    monkeypatch.setattr(
        project_execution_module,
        "CloudProviderSandbox",
        FakeCloudSandbox,
    )

    stages = []
    result = ProjectPlanningRunner().run(
        job_id="full-cycle-job",
        project_name="Governed Demo",
        objective="Build a governed demonstration workspace for project reviewers.",
        tenant_id="tenant-1",
        requested_by_id="user-1",
        stage_callback=lambda stage, progress: stages.append((stage, progress)),
    )

    assert result["success"] is True
    assert result["phase"] == 28
    assert result["mode"] == "full"
    assert result["approved"] is True
    assert result["requests_count"] == 8
    assert result["total_tokens"] == 3300
    assert result["calculated_cost"] == pytest.approx(0.013975)
    assert result["all_governance_layers_executed"] is True
    assert len(result["workforce"]) == 6
    assert result["delivery_package"]["contains_executable_product"] is True
    assert Path(result["output_directory"], "delivery-package").is_dir()
    assert (output_root / "full-cycle-job" / "execution-receipt.json").is_file()
    assert any(stage == "cognitive_review" for stage, _ in stages)
    assert any(stage == "external_research" for stage, _ in stages)
    assert any(stage == "governed_plan_review" for stage, _ in stages)
    assert any(stage == "plan_approved_for_implementation" for stage, _ in stages)
    assert any(stage == "implementation_tests" for stage, _ in stages)
    assert any(stage == "release_review" for stage, _ in stages)


def test_incomplete_provider_response_is_reported_without_raw_details() -> None:
    code, message = sanitized_execution_error(
        OpenAITransportError(
            "safe incomplete response",
            error_type="response_status",
            error_code="response_incomplete",
            error_param="max_output_tokens",
        )
    )
    assert code == "provider_incomplete"
    assert message == (
        "The provider response ended before the governed result was complete."
    )
    assert "max_output_tokens" not in message


def test_project_runner_uses_separate_web_search_capable_research_model(
    monkeypatch,
) -> None:
    import app.services.project_execution as project_execution_module

    monkeypatch.setattr(settings, "PROJECT_EXECUTION_LEGACY_MODEL", "gpt-5.6-luna")
    monkeypatch.setattr(
        settings,
        "PROJECT_EXECUTION_RESEARCH_MODEL",
        "gpt-5.6-luna",
    )
    monkeypatch.setattr(settings, "PROJECT_EXECUTION_BUDGET_CAP_USD", 0.05)
    monkeypatch.setattr(
        settings,
        "PROJECT_EXECUTION_WEB_SEARCH_COST_USD",
        0.01,
    )

    runner = ProjectPlanningRunner()

    assert runner.research_model == "gpt-5.6-luna"
    assert project_execution_module.MODEL_PRICING["gpt-5.6-luna"] == (0.20, 1.20)
    assert project_execution_module.RESEARCH_MODEL_PRICING[runner.research_model] == (
        0.20,
        1.20,
    )
    planning = 6 * ((4096 * 0.20) + (1200 * 1.20)) / 1_000_000
    research = 0.01 + ((16_384 * 0.20) + (3000 * 1.20)) / 1_000_000
    implementation = ((4096 * 0.20) + (3000 * 1.20)) / 1_000_000
    assert runner.budget_cap == pytest.approx(0.05)
    assert planning + research + implementation < runner.budget_cap


def test_project_runner_rejects_stale_legacy_planning_model_before_provider_use(
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "PROJECT_EXECUTION_LEGACY_MODEL", "gpt-5-mini")

    with pytest.raises(
        ProjectExecutionConfigurationError,
        match="legacy project execution model is not in the current-model allowlist",
    ):
        ProjectPlanningRunner()


def test_project_runner_rejects_unknown_research_model_before_provider_use(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        settings,
        "PROJECT_EXECUTION_RESEARCH_MODEL",
        "gpt-5-mini",
    )

    with pytest.raises(
        ProjectExecutionConfigurationError,
        match="research model is not in the fixed allowlist",
    ):
        ProjectPlanningRunner()


@pytest.mark.asyncio
async def test_organization_owner_closes_only_owner_approval_blocker_and_downloads_receipt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    suffix = uuid4().hex[:12]
    organization, user, _, project = await _create_project_tenant(suffix)
    output_root = tmp_path / "project-executions"
    evidence_root = output_root / f"execution-{suffix}" / "full-cycle" / "cycle"
    package_root = evidence_root / "delivery-package"
    package_root.mkdir(parents=True)
    (evidence_root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "phase": 28,
                "execution_id": "cycle",
                "review": {"approved": False},
            }
        ),
        encoding="utf-8",
    )
    (package_root / "index.html").write_text(
        "<!doctype html><title>Governed delivery</title>",
        encoding="utf-8",
    )
    (package_root / "manifest.json").write_text(
        json.dumps({"schema_version": 1, "files": ["index.html"]}),
        encoding="utf-8",
    )
    execution = ProjectExecution(
        id=f"approval-{suffix}",
        organization_id=organization.id,
        workspace_id=project.workspace_id,
        project_id=project.id,
        requested_by_id=user.id,
        mode="full",
        provider="openai",
        model="gpt-5-mini",
        status="completed",
        stage="rework_required",
        progress=100,
        objective=project.description or project.name,
        external_processing_confirmed=True,
        budget_cap_usd=0.05,
        calculated_cost_usd=0.02,
        requests_count=8,
        retries_count=0,
        input_tokens=1000,
        output_tokens=2000,
        total_tokens=3000,
        approved=False,
        readiness_score=1.0,
        result_summary={
            "success": True,
            "status": "rework_required",
            "phase": 28,
            "mode": "full",
            "provider": "openai",
            "model": "gpt-5-mini",
            "approved": False,
            "readiness_score": 1.0,
            "blocking_findings": ["owner approval is required"],
            "rework_plan": [
                "Request explicit Owner approval with the complete evidence package."
            ],
            "all_governance_layers_executed": True,
            "model_claims_used_as_execution_proof": False,
            "fallback_used": False,
            "production_modified": False,
            "governance": {
                "government": {
                    "owner_approval_required": True,
                    "owner_approved": False,
                    "verdict": "approved",
                }
            },
            "release_review": {
                "approved": False,
                "status": "rework_required",
                "owner_approval_required": True,
                "owner_approved": False,
                "blocking_findings": ["owner approval is required"],
                "rework_plan": [
                    "Request explicit Owner approval with the complete evidence package."
                ],
            },
            "delivery_package": {
                "contains_executable_product": True,
                "path": "delivery-package",
            },
        },
        evidence_path=str(evidence_root),
        attempts=1,
        max_attempts=1,
    )
    async with SessionLocal() as session:
        session.add(execution)
        await session.commit()

    monkeypatch.setattr(
        settings,
        "PROJECT_EXECUTION_OUTPUT_ROOT",
        str(output_root),
    )
    actor_holder = {
        "actor": _actor(user.id, organization.id, organization.name)
    }
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    app.dependency_overrides[current_user] = lambda: actor_holder["actor"]

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            manager_denied = await client.post(
                f"/api/v1/projects/{project.id}/executions/{execution.id}/approve",
                json={"confirm_owner_approval": True},
            )
            assert manager_denied.status_code == 403, manager_denied.text

            actor_holder["actor"] = _actor(
                user.id,
                organization.id,
                organization.name,
                role="Owner",
            )
            missing_confirmation = await client.post(
                f"/api/v1/projects/{project.id}/executions/{execution.id}/approve",
                json={"confirm_owner_approval": False},
            )
            assert missing_confirmation.status_code == 422

            approved = await client.post(
                f"/api/v1/projects/{project.id}/executions/{execution.id}/approve",
                json={
                    "confirm_owner_approval": True,
                    "note": "Reviewed the complete retained evidence package.",
                },
            )
            assert approved.status_code == 200, approved.text
            result = approved.json()
            assert result["approved"] is True
            assert result["stage"] == "approved"
            assert result["result"]["blocking_findings"] == []
            assert result["result"]["release_review"]["owner_approved"] is True
            assert result["result"]["owner_approval"]["approved"] is True

            duplicate = await client.post(
                f"/api/v1/projects/{project.id}/executions/{execution.id}/approve",
                json={"confirm_owner_approval": True},
            )
            assert duplicate.status_code == 200
            assert duplicate.json()["approved"] is True

            download = await client.get(
                f"/api/v1/projects/{project.id}/executions/{execution.id}/download"
            )
            assert download.status_code == 200, download.text
            archive = tmp_path / "approved-delivery.zip"
            archive.write_bytes(download.content)
            with zipfile.ZipFile(archive) as bundle:
                names = set(bundle.namelist())
                assert "index.html" in names
                assert "manifest.json" in names
                assert "owner-approval.json" in names
                receipt = json.loads(bundle.read("owner-approval.json"))
                assert receipt["decision"] == "approved"
                assert receipt["execution_id"] == execution.id
                assert receipt["approved_by_id"] == user.id

        async with SessionLocal() as session:
            stored = await session.get(ProjectExecution, execution.id)
            stored_project = await session.get(Project, project.id)
            assert stored is not None and stored.approved is True
            assert stored.stage == "approved"
            assert stored_project is not None
            assert stored_project.status == "completed"
            assert stored_project.progress == 100
            approval_events = (
                await session.scalars(
                    select(AuditEvent).where(
                        AuditEvent.resource_id == execution.id,
                        AuditEvent.action == "project.execution.owner_approved",
                    )
                )
            ).all()
            approval_notifications = (
                await session.scalars(
                    select(Notification).where(
                        Notification.recipient_id == user.id,
                        Notification.type == "project.execution.owner_approved",
                    )
                )
            ).all()
            assert len(approval_events) == 1
            assert len(approval_notifications) == 1
            assert (evidence_root / "owner-approval.json").is_file()
    finally:
        await _cleanup(organization.id)


@pytest.mark.asyncio
async def test_owner_approval_cannot_hide_other_release_blockers(
    tmp_path: Path,
    monkeypatch,
) -> None:
    suffix = uuid4().hex[:12]
    organization, user, _, project = await _create_project_tenant(suffix)
    output_root = tmp_path / "project-executions"
    evidence_root = output_root / f"blocked-{suffix}"
    evidence_root.mkdir(parents=True)
    (evidence_root / "manifest.json").write_text("{}", encoding="utf-8")
    execution = ProjectExecution(
        id=f"blocked-{suffix}",
        organization_id=organization.id,
        workspace_id=project.workspace_id,
        project_id=project.id,
        requested_by_id=user.id,
        mode="full",
        provider="openai",
        status="completed",
        stage="rework_required",
        progress=100,
        objective=project.description or project.name,
        external_processing_confirmed=True,
        budget_cap_usd=0.05,
        approved=False,
        readiness_score=0.9,
        result_summary={
            "blocking_findings": [
                "owner approval is required",
                "security:high:unresolved finding",
            ],
            "all_governance_layers_executed": True,
            "model_claims_used_as_execution_proof": False,
            "fallback_used": False,
            "production_modified": False,
            "release_review": {"owner_approval_required": True},
        },
        evidence_path=str(evidence_root),
        attempts=1,
        max_attempts=1,
    )
    async with SessionLocal() as session:
        session.add(execution)
        await session.commit()
    monkeypatch.setattr(settings, "PROJECT_EXECUTION_OUTPUT_ROOT", str(output_root))
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    app.dependency_overrides[current_user] = lambda: _actor(
        user.id,
        organization.id,
        organization.name,
        role="Owner",
    )
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                f"/api/v1/projects/{project.id}/executions/{execution.id}/approve",
                json={"confirm_owner_approval": True},
            )
            assert response.status_code == 409
        assert not (evidence_root / "owner-approval.json").exists()
    finally:
        await _cleanup(organization.id)


@pytest.mark.asyncio
async def test_provider_neutral_execution_is_snapshot_only_and_never_claims_governance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffix = uuid4().hex[:12]
    organization, user, _, project = await _create_project_tenant(suffix)
    actor = _actor(user.id, organization.id, organization.name)
    monkeypatch.setattr(
        "app.api.v1.endpoints.project_executions.settings.PROJECT_EXECUTION_OUTPUT_ROOT",
        str(tmp_path / "executions"),
    )
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    app.dependency_overrides[current_user] = lambda: actor
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                f"/api/v1/projects/{project.id}/executions",
                json={"mode": "provider_neutral", "confirm_external_processing": False},
            )
            assert response.status_code == 202, response.text
            execution = response.json()
            assert execution["status"] == "completed"
            assert execution["stage"] == "snapshot"
            assert execution["mode"] == "provider_neutral"
            assert execution["provider"] == "provider-neutral"
            assert execution["readiness_score"] == 0.0
            loaded = await client.get(
                f"/api/v1/projects/{project.id}/executions/{execution['id']}"
            )
            assert loaded.status_code == 200
            result = loaded.json()["result"]
            assert result["status"] == "snapshot"
            assert result["all_governance_layers_executed"] is False
            assert result["engineering_review"]["status"] == "not_executed"
            assert result["security_review"]["status"] == "not_executed"
            assert result["integration_review"]["status"] == "not_executed"
            assert result["release_review"]["status"] == "not_executed"
            assert "snapshot only" in result["claim_boundary"]
        async with SessionLocal() as session:
            durable_project = await session.get(Project, project.id)
            assert durable_project is not None
            assert durable_project.progress == 0
            assert durable_project.status == "planning"
            assert durable_project.review_status == "not_requested"
    finally:
        await _cleanup(organization.id)


def test_project_runner_withholds_implementation_when_governed_plan_requires_rework(
    tmp_path, monkeypatch
) -> None:
    from types import SimpleNamespace

    import app.services.project_execution as project_execution_module

    output_root = tmp_path / "output"
    local_reference = tmp_path / "local"
    local_reference.mkdir()
    (local_reference / "manifest.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(settings, "PROJECT_EXECUTION_OUTPUT_ROOT", str(output_root))
    monkeypatch.setattr(
        settings, "PROJECT_EXECUTION_LOCAL_REFERENCE", str(local_reference)
    )
    monkeypatch.setattr(settings, "PROJECT_EXECUTION_BUDGET_CAP_USD", 0.05)

    job_root = output_root / "plan-rework-job"
    research = job_root / "research"
    research.mkdir(parents=True)
    (research / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "mode": "controlled-web-research",
                "provider": "openai",
                "model": "gpt-5.4-nano",
                "request_count": 1,
                "search_calls": 1,
                "fallback_used": False,
                "production_modified": False,
                "sources": [
                    {"url": "https://standards.example.org/a", "domain": "standards.example.org"},
                    {"url": "https://guidance.example.net/b", "domain": "guidance.example.net"},
                ],
                "verified_facts": [
                    {"claim": "Retained evidence is required.", "confidence": 0.95},
                    {"claim": "Unsafe implementation must be withheld.", "confidence": 0.94},
                ],
                "recommended_constraints": ["Rework incomplete plans before implementation."],
                "input_tokens": 10,
                "output_tokens": 10,
                "total_tokens": 20,
                "calculated_cost": 0.001,
            }
        ),
        encoding="utf-8",
    )
    cloud = job_root / "cloud"
    cloud.mkdir()
    (cloud / "manifest.json").write_text(
        json.dumps(
            {
                "provider": "openai",
                "model": "gpt-5-mini",
                "execution_id": "cloud",
                "fallback_used": False,
                "production_modified": False,
                "artifacts": [],
                "requests_count": 6,
                "retries_count": 0,
                "input_tokens": 60,
                "output_tokens": 90,
                "total_tokens": 150,
                "calculated_cost": 0.002,
                "budget_cap": 0.05,
                "total_duration": 1.0,
                "review": {
                    "approved": False,
                    "readiness_score": 0.5,
                    "blocking_findings": ["Backend plan incomplete"],
                    "rework_plan": ["Complete Backend implementation sequence"],
                },
            }
        ),
        encoding="utf-8",
    )

    plan_manifest = job_root / "governance-plan" / "plan-review" / "manifest.json"

    class ReworkReviewer:
        def review(self, **kwargs):
            plan_manifest.parent.mkdir(parents=True, exist_ok=True)
            plan_manifest.write_text("{}", encoding="utf-8")
            return SimpleNamespace(
                approved=False,
                readiness_score=0.5,
                blocking_findings=("Backend: implementation sequence is incomplete",),
                rework_plan=("Backend: define concrete implementation steps",),
                manifest_path=plan_manifest,
                payload={
                    "approved": False,
                    "implementation_started": False,
                    "chief_engineer": {"approved": False},
                    "government": {"verdict": "approved"},
                },
            )

    class ForbiddenBuilder:
        MAX_INPUT_TOKENS = 4096
        MAX_OUTPUT_TOKENS = 3000

        def __init__(self, *args, **kwargs):
            raise AssertionError("implementation builder must not start after plan rework")

        @classmethod
        def load_result(cls, *args, **kwargs):
            raise AssertionError("implementation evidence must not load after plan rework")

    runner = ProjectPlanningRunner()
    monkeypatch.setattr(project_execution_module, "GovernedProjectPlanReviewer", ReworkReviewer)
    monkeypatch.setattr(project_execution_module, "ControlledProjectBuilder", ForbiddenBuilder)

    stages = []
    result = runner.run(
        job_id="plan-rework-job",
        project_name="Governed Demo",
        objective="Build a governed realtime member communications application.",
        requested_by_id="user-1",
        stage_callback=lambda stage, progress: stages.append((stage, progress)),
    )

    assert result["status"] == "rework_required"
    assert result["approved"] is False
    assert result["implementation"] is None
    assert result["all_governance_layers_executed"] is False
    assert result["plan_review"]["implementation_started"] is False
    assert any(stage == "governed_plan_review" for stage, _ in stages)
    assert any(stage == "plan_rework_required" for stage, _ in stages)
    assert not any(stage == "implementation_generation" for stage, _ in stages)
    assert (job_root / "plan-review-rework" / "delivery-package" / "PLAN_REVIEW.json").is_file()
