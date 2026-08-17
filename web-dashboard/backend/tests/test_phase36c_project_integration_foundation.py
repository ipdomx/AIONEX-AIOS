"""Phase 36C ProjectExecution integration foundation acceptance contracts."""
from __future__ import annotations

import asyncio
import json
import os
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select

from app.db.base import SessionLocal
from app.db.models import (
    AIProvider,
    AuditEvent,
    Notification,
    Organization,
    Project,
    ProjectAIRouteAttemptRecord,
    ProjectAIRoutePlanRecord,
    ProjectExecution,
    ProjectExecutionWorkerNode,
    ScopedMemory,
    User,
    Workspace,
)
from app.services.project_execution_ai_integration import (
    DeterministicProjectAIIntegrationRunner,
    ProjectAIIntegrationError,
    ProjectAIInvocation,
    ProjectAIInvocationFailure,
    ProjectAIInvocationResult,
    ProjectAIProjectMemoryAdapter,
)
from app.services.project_execution_routing import (
    ProjectAIProviderPolicy,
    ProjectAIScope,
    ProjectAITaskSpec,
)
from app.services.project_execution_worker import ProjectExecutionWorker

ROOT = Path(__file__).resolve().parents[1]


def _validated_model(
    model: str,
    *,
    tasks: tuple[str, ...] = ("reasoning", "coding"),
    local: bool = False,
    requests_per_minute: int = 100,
    concurrent_requests: int = 4,
) -> dict[str, object]:
    now = datetime.now(UTC)
    return {
        "model": model,
        "tasks": list(tasks),
        "evidence_ref": f"phase36c:integration:{model}",
        "validated_at": (now - timedelta(minutes=5)).isoformat(),
        "expires_at": (now + timedelta(days=1)).isoformat(),
        "languages": ["en", "ar"],
        "supports_tools": True,
        "supports_vision": False,
        "supports_audio": False,
        "local": local,
        "max_context_tokens": 32768,
        "quality_score": 0.9,
        "latency_score": 0.8,
        "privacy_score": 1.0 if local else 0.7,
        "input_cost_per_million": 1.0,
        "output_cost_per_million": 5.0,
        "requests_per_minute": requests_per_minute,
        "concurrent_requests": concurrent_requests,
        "circuit_failure_threshold": 3,
        "circuit_failure_window_seconds": 60,
        "circuit_open_seconds": 60,
        "lease_seconds": 30,
    }


async def _seed_execution(
    suffix: str,
    *,
    providers: tuple[tuple[str, str, bool], ...],
    max_attempts: int = 2,
    budget_cap_usd: float = 1.0,
) -> tuple[ProjectAIScope, str, str]:
    org = Organization(
        id=f"p36c-int-org-{suffix}",
        name=f"Phase 36C Integration {suffix}",
        slug=f"p36c-int-org-{suffix}",
        plan="enterprise",
        status="active",
    )
    user = User(
        id=f"p36c-int-user-{suffix}",
        organization_id=org.id,
        role_id=None,
        email=f"p36c-int-{suffix}@example.com",
        name="Phase 36C Integration User",
        password_hash="unused",
        status="active",
    )
    workspace = Workspace(
        id=f"p36c-int-ws-{suffix}",
        organization_id=org.id,
        name="Phase 36C Integration Workspace",
        slug=f"p36c-int-ws-{suffix}",
        status="active",
    )
    project = Project(
        id=f"p36c-int-project-{suffix}",
        organization_id=org.id,
        workspace_id=workspace.id,
        owner_id=user.id,
        name=f"Integration Project {suffix}",
        slug=f"p36c-int-project-{suffix}",
        description=f"Deterministic multi-provider integration objective {suffix}.",
        status="planning",
        priority="high",
        progress=0,
        tags=["phase36c", "integration"],
    )
    execution = ProjectExecution(
        id=f"p36c-int-exec-{suffix}",
        organization_id=org.id,
        workspace_id=workspace.id,
        project_id=project.id,
        requested_by_id=user.id,
        mode="full",
        provider="openai",
        status="queued",
        stage="queued",
        progress=0,
        objective=project.description,
        external_processing_confirmed=True,
        budget_cap_usd=budget_cap_usd,
        result_summary={},
        resource_class="project-build-cpu",
        priority_rank=100,
        attempts=0,
        max_attempts=max_attempts,
    )
    provider_rows = [
        AIProvider(
            id=f"p36c-int-provider-{provider_type}-{suffix}",
            organization_id=org.id,
            name=f"{provider_type} {suffix}",
            type=provider_type,
            status="connected",
            encrypted_api_key=None,
            base_url=None,
            config={
                "enabled": True,
                "validated_models": [
                    _validated_model(model, local=local)
                ],
            },
        )
        for provider_type, model, local in providers
    ]
    async with SessionLocal() as session:
        session.add(org)
        await session.flush()
        session.add_all([user, workspace])
        await session.flush()
        session.add(project)
        await session.flush()
        session.add(execution)
        session.add_all(provider_rows)
        await session.commit()
    return (
        ProjectAIScope(
            organization_id=org.id,
            workspace_id=workspace.id,
            project_id=project.id,
            execution_id=execution.id,
        ),
        org.id,
        user.id,
    )


async def _seed_second_project(
    base_scope: ProjectAIScope,
    *,
    suffix: str,
    requested_by_id: str,
    max_attempts: int = 2,
) -> ProjectAIScope:
    project = Project(
        id=f"p36c-int-project-{suffix}",
        organization_id=base_scope.organization_id,
        workspace_id=base_scope.workspace_id,
        owner_id=requested_by_id,
        name=f"Integration Project {suffix}",
        slug=f"p36c-int-project-{suffix}",
        description=f"Second deterministic integration objective {suffix}.",
        status="planning",
        priority="high",
        progress=0,
        tags=["phase36c", "integration", "second"],
    )
    execution = ProjectExecution(
        id=f"p36c-int-exec-{suffix}",
        organization_id=base_scope.organization_id,
        workspace_id=base_scope.workspace_id,
        project_id=project.id,
        requested_by_id=requested_by_id,
        mode="full",
        provider="openai",
        status="queued",
        stage="queued",
        progress=0,
        objective=project.description,
        external_processing_confirmed=True,
        budget_cap_usd=1.0,
        result_summary={},
        resource_class="project-build-cpu",
        priority_rank=100,
        attempts=0,
        max_attempts=max_attempts,
    )
    async with SessionLocal() as session:
        session.add(project)
        await session.flush()
        session.add(execution)
        await session.commit()
    return ProjectAIScope(
        organization_id=base_scope.organization_id,
        workspace_id=base_scope.workspace_id,
        project_id=project.id,
        execution_id=execution.id,
    )


async def _cleanup_org(organization_id: str) -> None:
    async with SessionLocal() as session:
        await session.execute(
            delete(AuditEvent).where(AuditEvent.organization_id == organization_id)
        )
        await session.execute(
            delete(Notification).where(Notification.organization_id == organization_id)
        )
        await session.execute(
            delete(ScopedMemory).where(ScopedMemory.organization_id == organization_id)
        )
        await session.execute(
            delete(ProjectExecution).where(
                ProjectExecution.organization_id == organization_id
            )
        )
        await session.execute(
            delete(AIProvider).where(AIProvider.organization_id == organization_id)
        )
        await session.execute(delete(Project).where(Project.organization_id == organization_id))
        await session.execute(
            delete(Workspace).where(Workspace.organization_id == organization_id)
        )
        await session.execute(delete(User).where(User.organization_id == organization_id))
        await session.execute(delete(Organization).where(Organization.id == organization_id))
        await session.commit()


async def _delete_workers(*worker_ids: str) -> None:
    async with SessionLocal() as session:
        await session.execute(
            delete(ProjectExecutionWorkerNode).where(
                ProjectExecutionWorkerNode.id.in_(worker_ids)
            )
        )
        await session.commit()


def _two_tasks(project_name: str, objective: str) -> tuple[ProjectAITaskSpec, ...]:
    return (
        ProjectAITaskSpec(
            task_id="planner",
            role="planner",
            task="reasoning",
            prompt=f"TOP-SECRET-PLAN::{project_name}::{objective}",
            max_tokens=200,
        ),
        ProjectAITaskSpec(
            task_id="coder",
            role="coder",
            task="coding",
            prompt=f"TOP-SECRET-CODE::{project_name}::{objective}",
            max_tokens=300,
            require_tools=True,
        ),
    )


def _one_coder(
    project_name: str,
    objective: str,
    *,
    failover: bool,
) -> tuple[ProjectAITaskSpec, ...]:
    return (
        ProjectAITaskSpec(
            task_id="coder",
            role="coder",
            task="coding",
            prompt=f"TOP-SECRET-CODE::{project_name}::{objective}",
            max_tokens=300,
            require_tools=True,
            allow_failover=failover,
            max_fallbacks=1 if failover else 0,
            provider_priority=("openai", "anthropic"),
        ),
    )


class RecordingInvoker:
    def __init__(self, label: str, *, fail: bool = False) -> None:
        self.label = label
        self.fail = fail
        self.calls: list[dict[str, object]] = []
        self._lock = threading.Lock()

    async def __call__(self, invocation: ProjectAIInvocation) -> ProjectAIInvocationResult:
        memory_notes = tuple(
            str(item.get("memory_note") or "")
            for item in invocation.memory
            if item.get("memory_note")
        )
        with self._lock:
            self.calls.append(
                {
                    "organization_id": invocation.scope.organization_id,
                    "task_id": invocation.task_id,
                    "role": invocation.role,
                    "provider": invocation.provider,
                    "model": invocation.model,
                    "memory_notes": memory_notes,
                }
            )
        await asyncio.sleep(0.01)
        if self.fail:
            raise ProjectAIInvocationFailure(
                "provider_transport",
                cost_usd=0.0001,
                latency_ms=8.0,
            )
        return ProjectAIInvocationResult(
            text=f"{self.label}:{invocation.role}:ok",
            cost_usd=0.0002,
            latency_ms=6.0,
            input_tokens=12,
            output_tokens=8,
            memory_note=f"{self.label}-{invocation.role}-memory",
        )


class BlockingInvoker(RecordingInvoker):
    def __init__(self, label: str, entered: threading.Event, release: threading.Event) -> None:
        super().__init__(label)
        self.entered = entered
        self.release = release

    async def __call__(self, invocation: ProjectAIInvocation) -> ProjectAIInvocationResult:
        memory_notes = tuple(
            str(item.get("memory_note") or "")
            for item in invocation.memory
            if item.get("memory_note")
        )
        with self._lock:
            self.calls.append(
                {
                    "organization_id": invocation.scope.organization_id,
                    "task_id": invocation.task_id,
                    "role": invocation.role,
                    "provider": invocation.provider,
                    "model": invocation.model,
                    "memory_notes": memory_notes,
                }
            )
        self.entered.set()
        released = await asyncio.to_thread(self.release.wait, 5)
        if not released:
            raise ProjectAIInvocationFailure("test_release_timeout")
        return ProjectAIInvocationResult(
            text=f"{self.label}:{invocation.role}:ok",
            cost_usd=0.0002,
            latency_ms=25.0,
            input_tokens=12,
            output_tokens=8,
            memory_note=f"{self.label}-{invocation.role}-memory",
        )


class ReleasingInvoker(RecordingInvoker):
    def __init__(self, label: str, entered: threading.Event, release: threading.Event) -> None:
        super().__init__(label)
        self.entered = entered
        self.release = release

    async def __call__(self, invocation: ProjectAIInvocation) -> ProjectAIInvocationResult:
        entered = await asyncio.to_thread(self.entered.wait, 5)
        if not entered:
            raise ProjectAIInvocationFailure("test_primary_not_entered")
        self.release.set()
        return await super().__call__(invocation)


def test_default_project_worker_remains_on_the_existing_planning_runner() -> None:
    source = (ROOT / "app/services/project_execution_worker.py").read_text()
    assert "runner or resolve_project_execution_runner()" in source
    assert "DeterministicProjectAIIntegrationRunner" not in source


@pytest.mark.asyncio
async def test_project_memory_adapter_rejects_cross_tenant_scope() -> None:
    left_suffix = uuid4().hex[:8]
    right_suffix = uuid4().hex[:8]
    left_scope, left_org, _ = await _seed_execution(
        left_suffix,
        providers=(("openai", "gpt-left", False),),
    )
    _, right_org, _ = await _seed_execution(
        right_suffix,
        providers=(("ollama", "qwen-right", True),),
    )
    adapter = ProjectAIProjectMemoryAdapter(SessionLocal)
    try:
        await adapter.verify_scope(left_scope)
        crossed = ProjectAIScope(
            organization_id=right_org,
            workspace_id=left_scope.workspace_id,
            project_id=left_scope.project_id,
            execution_id=left_scope.execution_id,
        )
        with pytest.raises(ProjectAIIntegrationError, match="scope does not match"):
            await adapter.recall(crossed)
    finally:
        await _cleanup_org(left_org)
        await _cleanup_org(right_org)


@pytest.mark.asyncio
async def test_two_project_workers_use_independent_provider_plans_and_project_memory() -> None:
    left_suffix = uuid4().hex[:8]
    right_suffix = uuid4().hex[:8]
    left_scope, left_org, _ = await _seed_execution(
        left_suffix,
        providers=(("openai", "gpt-left", False),),
    )
    right_scope, right_org, _ = await _seed_execution(
        right_suffix,
        providers=(("ollama", "qwen-right", True),),
    )
    openai = RecordingInvoker("openai")
    ollama = RecordingInvoker("ollama")
    policies = {
        left_org: ProjectAIProviderPolicy(allowed_providers=frozenset({"openai"})),
        right_org: ProjectAIProviderPolicy(allowed_providers=frozenset({"ollama"})),
    }
    runner = DeterministicProjectAIIntegrationRunner(
        session_factory=SessionLocal,
        redis_url=os.environ["REDIS_URL"],
        policy_resolver=lambda scope: policies[scope.organization_id],
        invokers={
            ("openai", "gpt-left"): openai,
            ("ollama", "qwen-right"): ollama,
        },
        task_factory=_two_tasks,
        redis_key_prefix=f"aionex:test:p36c:integration:{uuid4().hex}",
    )
    worker_a_id = f"p36c-integration-worker-a-{left_suffix}"
    worker_b_id = f"p36c-integration-worker-b-{right_suffix}"
    worker_a = ProjectExecutionWorker(
        runner=runner, worker_id=worker_a_id, capacity=1
    )
    worker_b = ProjectExecutionWorker(
        runner=runner, worker_id=worker_b_id, capacity=1
    )
    try:
        claim_a = await worker_a.claim()
        claim_b = await worker_b.claim()
        assert claim_a is not None and claim_b is not None
        assert claim_a[0] != claim_b[0]
        await asyncio.gather(
            worker_a.execute_claim(*claim_a),
            worker_b.execute_claim(*claim_b),
        )
        async with SessionLocal() as session:
            executions = list(
                (
                    await session.scalars(
                        select(ProjectExecution).where(
                            ProjectExecution.id.in_(
                                [left_scope.execution_id, right_scope.execution_id]
                            )
                        )
                    )
                ).all()
            )
            assert {row.status for row in executions} == {"completed"}
            provider_by_org = {row.organization_id: row.provider for row in executions}
            assert provider_by_org[left_org] == "openai"
            assert provider_by_org[right_org] == "ollama"
            memories = list(
                (
                    await session.scalars(
                        select(ScopedMemory).where(
                            ScopedMemory.organization_id.in_([left_org, right_org])
                        )
                    )
                ).all()
            )
            assert len(memories) == 4
            assert {
                (item.organization_id, item.scope_id) for item in memories
            } == {
                (left_org, left_scope.project_id),
                (right_org, right_scope.project_id),
            }
            rendered = json.dumps([item.value for item in memories], sort_keys=True)
            assert "TOP-SECRET" not in rendered
            assert "openai-planner-memory" in rendered
            assert "ollama-planner-memory" in rendered
            plans = list(
                (
                    await session.scalars(
                        select(ProjectAIRoutePlanRecord).where(
                            ProjectAIRoutePlanRecord.organization_id.in_([left_org, right_org])
                        )
                    )
                ).all()
            )
            assert len(plans) == 2
        openai_coder = next(item for item in openai.calls if item["role"] == "coder")
        ollama_coder = next(item for item in ollama.calls if item["role"] == "coder")
        assert "openai-planner-memory" in openai_coder["memory_notes"]
        assert "ollama-planner-memory" not in openai_coder["memory_notes"]
        assert "ollama-planner-memory" in ollama_coder["memory_notes"]
        assert "openai-planner-memory" not in ollama_coder["memory_notes"]
    finally:
        await _cleanup_org(left_org)
        await _cleanup_org(right_org)
        await _delete_workers(worker_a_id, worker_b_id)


@pytest.mark.asyncio
async def test_two_workers_share_provider_concurrency_and_use_approved_fallback() -> None:
    suffix = uuid4().hex[:8]
    left_scope, org_id, user_id = await _seed_execution(
        suffix,
        providers=(
            ("openai", "gpt-shared", False),
            ("anthropic", "claude-fallback", False),
        ),
    )
    right_scope = await _seed_second_project(
        left_scope,
        suffix=f"{suffix}-right",
        requested_by_id=user_id,
    )
    # Force both projects in this organization through one shared OpenAI slot.
    async with SessionLocal() as session:
        provider = await session.scalar(
            select(AIProvider).where(
                AIProvider.organization_id == org_id,
                AIProvider.type == "openai",
            )
        )
        assert provider is not None
        model = dict(provider.config["validated_models"][0])
        model["concurrent_requests"] = 1
        provider.config = {**provider.config, "validated_models": [model]}
        await session.commit()

    entered = threading.Event()
    release = threading.Event()
    openai = BlockingInvoker("openai", entered, release)
    anthropic = ReleasingInvoker("anthropic", entered, release)
    runner = DeterministicProjectAIIntegrationRunner(
        session_factory=SessionLocal,
        redis_url=os.environ["REDIS_URL"],
        policy_resolver=lambda _scope: ProjectAIProviderPolicy(
            allowed_providers=frozenset({"openai", "anthropic"})
        ),
        invokers={
            ("openai", "gpt-shared"): openai,
            ("anthropic", "claude-fallback"): anthropic,
        },
        task_factory=lambda project, objective: _one_coder(
            project, objective, failover=True
        ),
        redis_key_prefix=f"aionex:test:p36c:shared-worker:{uuid4().hex}",
    )
    worker_a_id = f"p36c-shared-worker-a-{suffix}"
    worker_b_id = f"p36c-shared-worker-b-{suffix}"
    worker_a = ProjectExecutionWorker(runner=runner, worker_id=worker_a_id, capacity=1)
    worker_b = ProjectExecutionWorker(runner=runner, worker_id=worker_b_id, capacity=1)
    try:
        first = await worker_a.claim()
        second = await worker_b.claim()
        assert first is not None and second is not None
        await asyncio.gather(
            worker_a.execute_claim(*first),
            worker_b.execute_claim(*second),
        )
        async with SessionLocal() as session:
            executions = list(
                (
                    await session.scalars(
                        select(ProjectExecution).where(
                            ProjectExecution.id.in_(
                                [left_scope.execution_id, right_scope.execution_id]
                            )
                        )
                    )
                ).all()
            )
            assert {row.status for row in executions} == {"completed"}
            assert {row.provider for row in executions} == {"openai", "anthropic"}
            fallback_rows = [
                row
                for row in executions
                if row.result_summary["provider_plan"][0]["fallback_used"] is True
            ]
            assert len(fallback_rows) == 1
            failures = fallback_rows[0].result_summary["provider_plan"][0][
                "prior_failures"
            ]
            assert failures == [
                {
                    "candidate_index": 0,
                    "error_code": "ProjectAIProviderConcurrencyLimited",
                }
            ]
            memories = list(
                (
                    await session.scalars(
                        select(ScopedMemory).where(ScopedMemory.organization_id == org_id)
                    )
                ).all()
            )
            assert len(memories) == 2
            assert {item.scope_id for item in memories} == {
                left_scope.project_id,
                right_scope.project_id,
            }
    finally:
        release.set()
        await _cleanup_org(org_id)
        await _delete_workers(worker_a_id, worker_b_id)


@pytest.mark.asyncio
async def test_integrated_worker_uses_approved_fallback_and_persists_provider() -> None:
    suffix = uuid4().hex[:8]
    scope, org_id, _ = await _seed_execution(
        suffix,
        providers=(
            ("openai", "gpt-primary", False),
            ("anthropic", "claude-fallback", False),
        ),
    )
    openai = RecordingInvoker("openai", fail=True)
    anthropic = RecordingInvoker("anthropic")
    runner = DeterministicProjectAIIntegrationRunner(
        session_factory=SessionLocal,
        redis_url=os.environ["REDIS_URL"],
        policy_resolver=lambda _scope: ProjectAIProviderPolicy(
            allowed_providers=frozenset({"openai", "anthropic"})
        ),
        invokers={
            ("openai", "gpt-primary"): openai,
            ("anthropic", "claude-fallback"): anthropic,
        },
        task_factory=lambda project, objective: _one_coder(
            project, objective, failover=True
        ),
        redis_key_prefix=f"aionex:test:p36c:fallback:{uuid4().hex}",
    )
    worker_id = f"p36c-fallback-worker-{suffix}"
    worker = ProjectExecutionWorker(runner=runner, worker_id=worker_id, capacity=1)
    try:
        claim = await worker.claim()
        assert claim is not None
        await worker.execute_claim(*claim)
        async with SessionLocal() as session:
            execution = await session.get(ProjectExecution, scope.execution_id)
            assert execution is not None
            assert execution.status == "completed"
            assert execution.provider == "anthropic"
            assert execution.retries_count == 1
            assert execution.result_summary["provider_plan"][0]["fallback_used"] is True
            attempts = list(
                (
                    await session.scalars(
                        select(ProjectAIRouteAttemptRecord)
                        .where(ProjectAIRouteAttemptRecord.organization_id == org_id)
                        .order_by(ProjectAIRouteAttemptRecord.attempt_index.asc())
                    )
                ).all()
            )
            assert [item.status for item in attempts] == ["failed", "succeeded"]
            assert [item.provider_type for item in attempts] == ["openai", "anthropic"]
            memory = list(
                (
                    await session.scalars(
                        select(ScopedMemory).where(ScopedMemory.organization_id == org_id)
                    )
                ).all()
            )
            assert len(memory) == 1
            assert memory[0].value["provider"] == "anthropic"
    finally:
        await _cleanup_org(org_id)
        await _delete_workers(worker_id)


@pytest.mark.asyncio
async def test_integrated_no_fallback_failure_returns_to_existing_retry_queue() -> None:
    suffix = uuid4().hex[:8]
    scope, org_id, _ = await _seed_execution(
        suffix,
        providers=(("openai", "gpt-only", False),),
        max_attempts=2,
    )
    openai = RecordingInvoker("openai", fail=True)
    runner = DeterministicProjectAIIntegrationRunner(
        session_factory=SessionLocal,
        redis_url=os.environ["REDIS_URL"],
        policy_resolver=lambda _scope: ProjectAIProviderPolicy(
            allowed_providers=frozenset({"openai"})
        ),
        invokers={("openai", "gpt-only"): openai},
        task_factory=lambda project, objective: _one_coder(
            project, objective, failover=False
        ),
        redis_key_prefix=f"aionex:test:p36c:no-fallback:{uuid4().hex}",
    )
    worker_id = f"p36c-no-fallback-worker-{suffix}"
    worker = ProjectExecutionWorker(runner=runner, worker_id=worker_id, capacity=1)
    try:
        claim = await worker.claim()
        assert claim is not None
        await worker.execute_claim(*claim)
        async with SessionLocal() as session:
            execution = await session.get(ProjectExecution, scope.execution_id)
            assert execution is not None
            assert execution.status == "queued"
            assert execution.stage == "retry_queued"
            assert execution.error_code == "execution_failed"
            memory_count = int(
                await session.scalar(
                    select(func.count(ScopedMemory.id)).where(
                        ScopedMemory.organization_id == org_id
                    )
                )
                or 0
            )
            attempts = list(
                (
                    await session.scalars(
                        select(ProjectAIRouteAttemptRecord).where(
                            ProjectAIRouteAttemptRecord.organization_id == org_id
                        )
                    )
                ).all()
            )
            assert memory_count == 0
            assert len(attempts) == 1 and attempts[0].status == "failed"
    finally:
        await _cleanup_org(org_id)
        await _delete_workers(worker_id)
