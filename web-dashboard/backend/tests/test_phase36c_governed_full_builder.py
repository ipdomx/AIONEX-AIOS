"""Phase36C real durable worker -> safe generated application -> complete governance.

Integration tests require disposable synthetic PostgreSQL and Redis, not the
production customer database or actual paid model invocations.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import zipfile
from pathlib import Path
from uuid import uuid4

import pytest

from aios.project_ai_governed_compiler import ProjectAIGovernedCompiler
from app.db.base import SessionLocal
from app.db.models import ProjectExecution, OwnerControlRecord
from app.core.config import settings
from app.core.auth import UserRecord
from app.api.v1.endpoints.project_executions import download_project_execution, serialize_project_execution
from app.services.host_maintenance_admission import DOMAIN, RESOURCE_ID, SCHEMA_VERSION, SCOPE
from sqlalchemy import select, delete
from app.services.project_execution_ai_integration import (
    DeterministicProjectAIIntegrationRunner,
    ProjectAIIntegrationError,
    ProjectAIInvocation,
    ProjectAIInvocationResult,
    default_project_ai_tasks,
)
from app.services.project_execution_routing import ProjectAIProviderPolicy
from app.services.project_execution_worker import ProjectExecutionWorker
from test_phase36c_project_integration_foundation import (
    _cleanup_org,
    _delete_workers,
    _seed_execution,
)


def _specification() -> dict:
    """Mirror the controlled-builder fixture without importing the root test package."""

    return {
        "schema_version": 3,
        "application_type": "web_application",
        "title": "Governed Project Workspace",
        "tagline": "A transparent workflow for controlled project delivery.",
        "summary": (
            "This prototype organizes the project objective, workflow and retained "
            "evidence without claiming production deployment."
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
            "logo_concept": "A precise geometric project mark",
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
                    "steps": [
                        "validate input",
                        "persist record",
                        "return governed result",
                    ],
                }
            ],
        },
        "sections": [
            {
                "id": "overview",
                "title": "Project overview",
                "body": "Understand the requested outcome and the intended audience.",
                "items": ["Objective summary", "Audience and value"],
            },
            {
                "id": "workflow",
                "title": "Governed workflow",
                "body": "Follow the controlled stages from intake through review.",
                "items": ["Council review", "Engineering delivery"],
            },
            {
                "id": "evidence",
                "title": "Evidence boundary",
                "body": "Inspect what is proven and what still requires implementation.",
                "items": ["Retained hashes", "Explicit limitations"],
            },
        ],
        "primary_action": "Review workflow",
        "secondary_action": "Inspect evidence",
        "limitations": [
            "No production deployment or external integration is claimed."
        ],
    }


class BoundedSpecInvoker:
    def __init__(self, *, valid: bool = True) -> None:
        self.valid = valid
        self.calls: list[str] = []

    async def __call__(self, invocation: ProjectAIInvocation) -> ProjectAIInvocationResult:
        self.calls.append(invocation.role)
        if invocation.role == "coder" and self.valid:
            text = json.dumps(_specification())
        elif invocation.role == "coder":
            text = "import os; print('arbitrary unreviewed model code')"
        else:
            text = f"Review role {invocation.role} completed planning, without claiming tests."
        return ProjectAIInvocationResult(
            text=text,
            cost_usd=0.0001,
            latency_ms=4,
            input_tokens=14,
            output_tokens=24,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("valid", [True, False])
async def test_real_durable_worker_builds_and_governs_or_requires_rework(
    tmp_path: Path, valid: bool,
) -> None:
    suffix = uuid4().hex[:8]
    scope, org, user_id = await _seed_execution(
        suffix,
        providers=(("ollama", f"qwen-safe-{suffix}", True),),
    )
    # Tests are synthetic; the durable admission authority is seeded only in
    # an explicitly nonproduction test database. Never bypass/seed live admission.
    assert settings.ENVIRONMENT.lower() in {"test", "testing", "ci"}
    created_admission = False
    async with SessionLocal() as session:
        existing = await session.scalar(select(OwnerControlRecord).where(
            OwnerControlRecord.domain == DOMAIN,
            OwnerControlRecord.resource_id == RESOURCE_ID,
        ))
        if existing is None:
            session.add(OwnerControlRecord(
                domain=DOMAIN, resource_id=RESOURCE_ID, status="open",
                enabled=True, version=1,
                payload={
                    "schema_version": SCHEMA_VERSION,
                    "scope": SCOPE,
                    "generation": 1,
                    "operation_id": None,
                    "reason": "migration-seed",
                    "changed_at": None,
                    "full_host_closure": False,
                },
            ))
            await session.commit()
            created_admission = True
        else:
            assert existing.status == "open" and existing.enabled is True
    invoker = BoundedSpecInvoker(valid=valid)
    runner = DeterministicProjectAIIntegrationRunner(
        session_factory=SessionLocal,
        redis_url=os.environ["REDIS_URL"],
        policy_resolver=lambda _scope: ProjectAIProviderPolicy(
            allowed_providers=frozenset({"ollama"}),
        ),
        invokers={("ollama", f"qwen-safe-{suffix}"): invoker},
        task_factory=default_project_ai_tasks,
        governed_compiler=ProjectAIGovernedCompiler(tmp_path / "executions"),
        redis_key_prefix=f"aionex:test:full-governed:{uuid4().hex}",
    )
    worker = ProjectExecutionWorker(
        runner=runner, worker_id=f"full-engine-worker-{suffix}", capacity=1,
    )
    try:
        claim = await worker.claim()
        assert claim is not None and claim[0] == scope.execution_id
        await worker.execute_claim(*claim)
        assert invoker.calls == ["planner", "researcher", "coder", "reviewer"]
        async with SessionLocal() as session:
            row = await session.get(ProjectExecution, scope.execution_id)
            assert row is not None
            assert row.status == "completed"
            assert row.stage == "rework_required"
            assert row.approved is False
            assert row.requests_count == 4
            summary = dict(row.result_summary)
            assert summary["approved"] is False
            assert summary["release_approval_withheld"] is True
            assert summary["calculated_cost"] > 0
            public = serialize_project_execution(row)
            if valid:
                assert public["evidence_available"] is True
                assert public["result"]["all_governance_layers_executed"] is True
                assert public["result"]["delivery_package"]["contains_executable_product"] is True
                assert public["result"]["release_review"]["approved"] is False
                assert summary["all_governance_layers_executed"] is True
                assert summary["delivery_package"]["contains_executable_product"] is True
                assert summary["implementation"]["tests_passed"] is True
                assert summary["implementation"]["rollback_tested"] is True
                assert len(summary["workforce"]) == 6
                assert "research verification failed" in summary["blocking_findings"]
                assert (Path(summary["output_directory"]) / "delivery-package/source/server.py").is_file()
                assert Path(summary["project_archive_path"]).is_file()
                actor = UserRecord(
                    id=user_id, email="synthetic@example.invalid",
                    name="Synthetic Member", role="User", password_hash="unused",
                    organization_id=org, organization_name="Test Organization",
                    organization_plan="enterprise", permissions=["projects:read"],
                )
                package = await download_project_execution(
                    scope.project_id, scope.execution_id,
                    actor=actor, session=session,
                )
                content = b"".join([chunk async for chunk in package.body_iterator])
                assert hashlib.sha256(content).hexdigest() == package.headers["X-AIONEX-SHA256"]
                with zipfile.ZipFile(io.BytesIO(content)) as archive:
                    assert "source/server.py" in archive.namelist()
                    assert "source/index.html" in archive.namelist()
                    assert "source/PROJECT_PROFILE.json" in archive.namelist()
                    assert "README.md" in archive.namelist()
            else:
                assert summary["all_governance_layers_executed"] is False
                assert summary["delivery_package"]["contains_executable_product"] is False
                assert any("specification" in x.lower() for x in summary["blocking_findings"])
                assert not (tmp_path / "executions" / scope.execution_id).exists()
    finally:
        await _cleanup_org(org)
        await _delete_workers(worker.worker_id)
        if created_admission:
            async with SessionLocal() as session:
                await session.execute(delete(OwnerControlRecord).where(
                    OwnerControlRecord.domain == DOMAIN,
                    OwnerControlRecord.resource_id == RESOURCE_ID,
                ))
                await session.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("ready", [True, False])
async def test_3d_full_uses_existing_verified_delivery_and_never_fakes_release(
    tmp_path: Path, ready: bool,
) -> None:
    suffix = uuid4().hex[:8]
    scope, org, user_id = await _seed_execution(
        suffix, providers=(("ollama", f"qwen-3d-{suffix}", True),),
    )

    class Stub3DBuilder:
        def build(self, *, project_id, project_name, objective, execution_root, asset_manifest_path):
            assert project_id == scope.project_id
            assert asset_manifest_path is None
            destination = Path(execution_root) / "delivery-package" / "3d-web"
            destination.mkdir(parents=True)
            (destination / "index.html").write_text("<!doctype html><title>Verified 3D mock build</title>")
            return {
                "mode": "3d_full", "runtime": "react-three-fiber",
                "delivery_path": "delivery-package/3d-web",
                "aggregate_sha256": "a" * 64,
                "asset_count": 0, "release_ready": ready,
                "release_reasons": [] if ready else ["mobile browser QA failed"],
                "browser_qa_passed": ready, "performance_passed": ready,
                "production_build_passed": ready,
            }

    runner = DeterministicProjectAIIntegrationRunner(
        session_factory=SessionLocal,
        redis_url=os.environ["REDIS_URL"],
        policy_resolver=lambda _scope: ProjectAIProviderPolicy(
            allowed_providers=frozenset({"ollama"}),
        ),
        invokers={("ollama", f"qwen-3d-{suffix}"): BoundedSpecInvoker()},
        task_factory=default_project_ai_tasks,
        governed_compiler=ProjectAIGovernedCompiler(tmp_path / "results"),
        three_d_builder=Stub3DBuilder(),
        redis_key_prefix=f"aionex:test:3d-full:{uuid4().hex}",
    )
    try:
        result = await runner._run_async(
            job_id=scope.execution_id,
            project_name="3D Full Project",
            objective="Build a governed website with reviewed 3D experience and source.",
            tenant_id=org,
            requested_by_id=user_id,
            execution_mode="3d_full",
            project_id=scope.project_id,
            stage_callback=None,
        )
        assert result["all_governance_layers_executed"] is True
        assert result["three_d_web"]["release_ready"] is ready
        assert result["approved"] is False  # External independent research is still missing.
        assert result["delivery_package"]["contains_executable_product"] is True
        assert result["delivery_package"]["three_d_web_sha256"] == "a" * 64
        assert result["release_review"]["three_d_web"]["release_ready"] is ready
        if not ready:
            assert any("3D web:" in item for item in result["blocking_findings"])
            assert result["release_review"]["status"] == "rework_required"
        assert (Path(result["output_directory"]) / "delivery-package/3d-web/index.html").is_file()
    finally:
        await _cleanup_org(org)


def test_3d_full_requires_valid_explicit_builder_and_project_identity() -> None:
    runner = DeterministicProjectAIIntegrationRunner(
        session_factory=SessionLocal, redis_url="redis://127.0.0.1:6379/0",
        policy_resolver=lambda scope: ProjectAIProviderPolicy(
            allowed_providers=frozenset({"ollama"})
        ),
        default_invoker=BoundedSpecInvoker(),
    )
    with pytest.raises(ProjectAIIntegrationError, match="3D full delivery requires"):
        runner.run(
            job_id="synthetic", project_name="Synthetic App",
            objective="Build a genuine complete 3D application with reviewed source.",
            execution_mode="3d_full", project_id="project-1",
        )


@pytest.mark.asyncio
async def test_durable_planning_mode_retains_six_department_package_without_false_release(
    tmp_path: Path,
) -> None:
    suffix = uuid4().hex[:8]
    scope, org, user_id = await _seed_execution(
        suffix, providers=(("ollama", f"qwen-planning-{suffix}", True),)
    )
    async with SessionLocal() as session:
        record = await session.get(ProjectExecution, scope.execution_id)
        assert record is not None
        record.mode = "planning"
        await session.commit()
    runner = DeterministicProjectAIIntegrationRunner(
        session_factory=SessionLocal,
        redis_url=os.environ["REDIS_URL"],
        policy_resolver=lambda _scope: ProjectAIProviderPolicy(
            allowed_providers=frozenset({"ollama"}),
        ),
        invokers={("ollama", f"qwen-planning-{suffix}"): BoundedSpecInvoker()},
        task_factory=default_project_ai_tasks,
        governed_compiler=ProjectAIGovernedCompiler(tmp_path / "planning"),
        redis_key_prefix=f"aionex:test:planning-governed:{uuid4().hex}",
    )
    try:
        result = await runner._run_async(
            job_id=scope.execution_id,
            project_name="Planning Project",
            objective="Build a validated project engineering plan with departments and evidence.",
            tenant_id=org,
            requested_by_id=user_id,
            execution_mode="planning",
            project_id=scope.project_id,
            stage_callback=None,
        )
        assert result["planning_approved"] is True
        assert result["approved"] is False
        assert result["all_governance_layers_executed"] is False
        assert result["delivery_package"]["contains_executable_product"] is False
        assert result["release_approval_withheld_reason"] == "planning_only"
        async with SessionLocal() as session:
            execution = await session.get(ProjectExecution, scope.execution_id)
            assert execution is not None
            assert execution.status == "queued"
        planned = Path(result["output_directory"]) / "delivery-package/engineering-plan.json"
        assert planned.is_file()
        assert len(json.loads(planned.read_text())["departments"]) == 6
    finally:
        await _cleanup_org(org)


@pytest.mark.asyncio
async def test_external_processing_without_user_consent_never_routes_a_model(
    tmp_path: Path,
) -> None:
    suffix = uuid4().hex[:8]
    scope, org, user_id = await _seed_execution(
        suffix, providers=(("ollama", f"qwen-consent-{suffix}", True),)
    )
    async with SessionLocal() as session:
        record = await session.get(ProjectExecution, scope.execution_id)
        assert record is not None
        record.external_processing_confirmed = False
        await session.commit()
    invoker = BoundedSpecInvoker()
    runner = DeterministicProjectAIIntegrationRunner(
        session_factory=SessionLocal,
        redis_url=os.environ["REDIS_URL"],
        policy_resolver=lambda _scope: ProjectAIProviderPolicy(
            allowed_providers=frozenset({"ollama"}),
            offline_only=False,
        ),
        invokers={("ollama", f"qwen-consent-{suffix}"): invoker},
        task_factory=default_project_ai_tasks,
        governed_compiler=ProjectAIGovernedCompiler(tmp_path / "generated"),
        redis_key_prefix=f"aionex:test:refuse-external-processing:{uuid4().hex}",
    )
    try:
        with pytest.raises(ProjectAIIntegrationError, match="external processing was not authorized"):
            await runner._run_async(
                job_id=scope.execution_id,
                project_name="No external authorization",
                objective="Build a complete project while respecting user privacy.",
                tenant_id=org,
                requested_by_id=user_id,
                project_id=scope.project_id,
                execution_mode="full",
                stage_callback=None,
            )
        assert invoker.calls == []
        assert not (tmp_path / "generated").exists()
    finally:
        await _cleanup_org(org)


@pytest.mark.asyncio
async def test_bounded_real_local_model_brief_follows_all_reviewed_compiler_gates(
    tmp_path: Path,
) -> None:
    suffix = uuid4().hex[:8]
    scope, org, user = await _seed_execution(
        suffix, providers=(("ollama", f"qwen-compact-{suffix}", True),)
    )

    async with SessionLocal() as session:
        execution = await session.get(ProjectExecution, scope.execution_id)
        assert execution is not None
        execution.external_processing_confirmed = False
        await session.commit()

    class CompactInvoker(BoundedSpecInvoker):
        async def __call__(self, invocation):
            if invocation.role != "coder":
                return await super().__call__(invocation)
            from tests.test_project_ai_compact_spec import _brief
            self.calls.append("coder")
            return ProjectAIInvocationResult(
                text=json.dumps(_brief()), cost_usd=0,
                latency_ms=1.0, input_tokens=32, output_tokens=120,
            )

    invoker = CompactInvoker()
    runner = DeterministicProjectAIIntegrationRunner(
        session_factory=SessionLocal,
        redis_url=os.environ["REDIS_URL"],
        policy_resolver=lambda _scope: ProjectAIProviderPolicy(
            allowed_providers=frozenset({"ollama"}),
            offline_only=True,
            privacy_mode=True,
        ),
        invokers={("ollama", f"qwen-compact-{suffix}"): invoker},
        task_factory=default_project_ai_tasks,
        governed_compiler=ProjectAIGovernedCompiler(tmp_path / "projects"),
        redis_key_prefix=f"aionex:test:compact-local-full:{uuid4().hex}",
    )
    try:
        result = await runner._run_async(
            job_id=scope.execution_id,
            project_name="Local Task Manager",
            objective="Build an offline-first task manager with reviewed local records.",
            tenant_id=org,
            requested_by_id=user,
            project_id=scope.project_id,
            execution_mode="full",
            stage_callback=None,
        )
        assert result["all_governance_layers_executed"] is True
        assert result["approved"] is False
        assert result["delivery_package"]["contains_executable_product"] is True
        assert result["implementation"]["tests_passed"] is True
        assert result["implementation"]["rollback_tested"] is True
        assert len(result["workforce"]) == 6
        assert (Path(result["output_directory"]) / "delivery-package/source/targets/api/app.py").is_file()
        build = Path(result["output_directory"]).parent.parent / "implementation/manifest.json"
        assert json.loads(build.read_text())["source_specification_kind"] == "bounded-local-brief"
        full_manifest = json.loads(Path(result["manifest_path"]).read_text())
        assert full_manifest["intake"]["external_processing_authorized"] is False
        assert full_manifest["intake"]["local_processing_authorized"] is True
        assert invoker.calls == ["planner", "researcher", "coder", "reviewer"]
    finally:
        await _cleanup_org(org)



@pytest.mark.asyncio
async def test_3d_provider_failure_returns_rework_without_discarding_verified_core_app(
    tmp_path: Path,
) -> None:
    from app.services.three_d_project_delivery import ThreeDProjectDeliveryError

    suffix = uuid4().hex[:8]
    scope, org, user = await _seed_execution(
        suffix, providers=(("ollama", f"qwen-3d-failure-{suffix}", True),),
    )

    class Failing3D:
        def build(self, **_kwargs):
            raise ThreeDProjectDeliveryError("provider token should not reach user")

    runner = DeterministicProjectAIIntegrationRunner(
        session_factory=SessionLocal,
        redis_url=os.environ["REDIS_URL"],
        policy_resolver=lambda _scope: ProjectAIProviderPolicy(
            allowed_providers=frozenset({"ollama"}),
            offline_only=True,
            privacy_mode=True,
        ),
        invokers={("ollama", f"qwen-3d-failure-{suffix}"): BoundedSpecInvoker()},
        task_factory=default_project_ai_tasks,
        governed_compiler=ProjectAIGovernedCompiler(tmp_path / "generated"),
        three_d_builder=Failing3D(),
        redis_key_prefix=f"aionex:test:3d-provider-failure:{uuid4().hex}",
    )
    try:
        result = await runner._run_async(
            job_id=scope.execution_id,
            project_name="Safe 3D Core App",
            objective="Build a verified website with a 3D visual layer and local persistence.",
            tenant_id=org,
            requested_by_id=user,
            execution_mode="3d_full",
            project_id=scope.project_id,
            stage_callback=None,
        )
        assert result["approved"] is False
        assert result["status"] == "rework_required"
        assert result["three_d_web"]["release_ready"] is False
        assert not result["three_d_web"].get("aggregate_sha256")
        assert "three_d_web" not in result["delivery_package"]
        assert result["delivery_package"]["contains_executable_product"] is True
        assert any("3D web:" in reason for reason in result["blocking_findings"])
        assert all("provider token" not in reason for reason in result["blocking_findings"])
        assert (Path(result["output_directory"]) / "delivery-package/source/server.py").is_file()
        assert Path(result["project_archive_path"]).is_file()
    finally:
        await _cleanup_org(org)


@pytest.mark.asyncio
async def test_3d_full_local_privacy_mode_does_not_call_configured_paid_builder(
    tmp_path: Path,
) -> None:
    from unittest.mock import patch

    suffix = uuid4().hex[:8]
    scope, org, user = await _seed_execution(
        suffix, providers=(("ollama", f"local-3d-{suffix}", True),)
    )
    async with SessionLocal() as session:
        execution = await session.get(ProjectExecution, scope.execution_id)
        assert execution is not None
        execution.external_processing_confirmed = False
        await session.commit()

    class ForbiddenExternal3D:
        calls = 0

        def build(self, **_kwargs):
            self.calls += 1
            raise AssertionError("local-only users cannot spend external 3D credits")

    builder = ForbiddenExternal3D()
    runner = DeterministicProjectAIIntegrationRunner(
        session_factory=SessionLocal,
        redis_url=os.environ["REDIS_URL"],
        policy_resolver=lambda _scope: ProjectAIProviderPolicy(
            allowed_providers=frozenset({"ollama"}),
            offline_only=True,
            privacy_mode=True,
        ),
        invokers={("ollama", f"local-3d-{suffix}"): BoundedSpecInvoker()},
        task_factory=default_project_ai_tasks,
        governed_compiler=ProjectAIGovernedCompiler(tmp_path / "generated"),
        three_d_builder=builder,
        redis_key_prefix=f"aionex:test:3d-no-external-consent:{uuid4().hex}",
    )
    try:
        with patch.dict(os.environ, {"TRIPO_API_KEY": "synthetic-unusable-provider-key"}):
            result = await runner._run_async(
                job_id=scope.execution_id,
                project_name="Local 3D Workspace",
                objective="Make a reviewed local 3D-capable application without external credit purchases.",
                tenant_id=org,
                requested_by_id=user,
                execution_mode="3d_full",
                project_id=scope.project_id,
                stage_callback=None,
            )
        assert builder.calls == 0
        assert result["approved"] is False
        assert result["three_d_web"]["release_ready"] is False
        assert result["delivery_package"]["contains_executable_product"] is True
        assert not result["delivery_package"].get("three_d_web")
        assert any("3D web:" in finding for finding in result["blocking_findings"])
        assert Path(result["project_archive_path"]).is_file()
    finally:
        await _cleanup_org(org)
