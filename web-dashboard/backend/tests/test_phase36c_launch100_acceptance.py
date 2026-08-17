"""Phase 36C launch acceptance for 100 isolated live-project consumers."""
from __future__ import annotations

import asyncio
import statistics
import threading
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select

from app.db.base import SessionLocal
from app.db.models import (
    AIProvider,
    Organization,
    Project,
    ProjectAIRouteAttemptRecord,
    ProjectExecution,
    ScopedMemory,
    User,
    Workspace,
)
from app.services.project_execution_ai_integration import (
    DeterministicProjectAIIntegrationRunner,
    ProjectAIInvocation,
    ProjectAIInvocationResult,
)
from app.services.project_execution_routing import ProjectAIProviderPolicy, ProjectAITaskSpec
from app.services.project_execution_worker import ProjectExecutionWorker


class LaunchInvoker:
    def __init__(self, provider: str, *, cost_usd: float) -> None:
        self.provider = provider
        self.cost_usd = cost_usd
        self.calls: list[tuple[str, str, str]] = []
        self._lock = threading.Lock()

    async def __call__(self, invocation: ProjectAIInvocation) -> ProjectAIInvocationResult:
        with self._lock:
            self.calls.append(
                (
                    invocation.scope.organization_id,
                    invocation.scope.project_id,
                    invocation.model,
                )
            )
        await asyncio.sleep(0.003)
        return ProjectAIInvocationResult(
            text=f"{self.provider}:{invocation.scope.project_id}:ok",
            cost_usd=self.cost_usd,
            latency_ms=3.0,
            input_tokens=8,
            output_tokens=6,
            memory_note=f"{self.provider}-project-memory",
        )


def _validated_model(
    model: str,
    *,
    local: bool,
    input_cost: float,
    output_cost: float,
) -> dict[str, object]:
    now = datetime.now(UTC)
    return {
        "model": model,
        "tasks": ["reasoning"],
        "evidence_ref": f"phase36c:launch100:{model}",
        "policy_ref": f"phase36c:launch100-policy:{model}",
        "validated_at": (now - timedelta(minutes=1)).isoformat(),
        "expires_at": (now + timedelta(hours=2)).isoformat(),
        "languages": ["en", "ar"],
        "supports_tools": False,
        "supports_vision": False,
        "supports_audio": False,
        "local": local,
        "max_context_tokens": 32768,
        "quality_score": 0.8,
        "latency_score": 0.8,
        "privacy_score": 1.0 if local else 0.7,
        "input_cost_per_million": input_cost,
        "output_cost_per_million": output_cost,
        "requests_per_minute": 10000,
        "concurrent_requests": 6,
        "circuit_failure_threshold": 5,
        "circuit_failure_window_seconds": 60,
        "circuit_open_seconds": 30,
        "lease_seconds": 60,
    }


def _single_task(project_name: str, objective: str) -> tuple[ProjectAITaskSpec, ...]:
    return (
        ProjectAITaskSpec(
            task_id="planner",
            role="planner",
            task="reasoning",
            prompt=f"Launch acceptance plan for {project_name}: {objective}",
            max_tokens=128,
            allow_failover=False,
            max_fallbacks=0,
        ),
    )


@pytest.mark.asyncio
async def test_launch100_users_complete_isolated_projects_under_bounded_workers() -> None:
    suffix = uuid4().hex[:10]
    platform_org_id = f"launch100-platform-{suffix}"
    consumer_prefix = f"launch100-org-{suffix}-"
    provider_ids = {
        "ollama": f"l100-p-ollama-{suffix}",
        "mistral": f"l100-p-mistral-{suffix}",
        "deepseek": f"l100-p-deepseek-{suffix}",
    }
    policies: dict[str, ProjectAIProviderPolicy] = {}
    execution_ids: list[str] = []
    project_ids: list[str] = []
    started = time.monotonic()

    free_invoker = LaunchInvoker("ollama", cost_usd=0.0)
    paid_invoker = LaunchInvoker("mistral", cost_usd=0.0001)
    override_invoker = LaunchInvoker("deepseek", cost_usd=0.0001)

    try:
        async with SessionLocal() as session:
            session.add(
                Organization(
                    id=platform_org_id,
                    name="Launch 100 Platform Pool",
                    slug=platform_org_id,
                    plan="enterprise",
                    status="active",
                )
            )
            await session.flush()
            session.add_all(
                [
                    AIProvider(
                        id=provider_ids["ollama"],
                        organization_id=platform_org_id,
                        name="Launch Free Ollama",
                        type="ollama",
                        status="connected",
                        base_url="http://ollama:11434",
                        config={
                            "enabled": True,
                            "validated_models": [
                                _validated_model(
                                    "gemma3:4b",
                                    local=True,
                                    input_cost=0.0,
                                    output_cost=0.0,
                                )
                            ],
                        },
                    ),
                    AIProvider(
                        id=provider_ids["mistral"],
                        organization_id=platform_org_id,
                        name="Launch Paid Mistral",
                        type="mistral",
                        status="connected",
                        config={
                            "enabled": True,
                            "validated_models": [
                                _validated_model(
                                    "mistral-current-paid",
                                    local=False,
                                    input_cost=0.2,
                                    output_cost=0.6,
                                )
                            ],
                        },
                    ),
                    AIProvider(
                        id=provider_ids["deepseek"],
                        organization_id=platform_org_id,
                        name="Launch Paid Override",
                        type="deepseek",
                        status="connected",
                        config={
                            "enabled": True,
                            "validated_models": [
                                _validated_model(
                                    "deepseek-current-paid",
                                    local=False,
                                    input_cost=0.2,
                                    output_cost=0.6,
                                )
                            ],
                        },
                    ),
                ]
            )
            await session.flush()

            for index in range(100):
                org_id = f"{consumer_prefix}{index:03d}"
                user_id = f"launch100-user-{suffix}-{index:03d}"
                workspace_id = f"launch100-ws-{suffix}-{index:03d}"
                project_id = f"launch100-project-{suffix}-{index:03d}"
                execution_id = f"launch100-exec-{suffix}-{index:03d}"
                project_ids.append(project_id)
                execution_ids.append(execution_id)
                access = "free" if index < 50 else ("paid" if index < 90 else "override")
                session.add_all(
                    [
                        Organization(
                            id=org_id,
                            name=f"Launch Consumer {index}",
                            slug=org_id,
                            plan="free" if access == "free" else "enterprise",
                            status="active",
                        ),
                        User(
                            id=user_id,
                            organization_id=org_id,
                            role_id=None,
                            email=f"launch100-{suffix}-{index:03d}@example.com",
                            name=f"Launch User {index}",
                            password_hash="unused",
                            status="active",
                        ),
                        Workspace(
                            id=workspace_id,
                            organization_id=org_id,
                            name=f"Launch Workspace {index}",
                            slug=workspace_id,
                            status="active",
                        ),
                    ]
                )
                await session.flush()
                session.add(
                    Project(
                        id=project_id,
                        organization_id=org_id,
                        workspace_id=workspace_id,
                        owner_id=user_id,
                        name=f"Launch Project {index}",
                        slug=project_id,
                        description="Produce one isolated governed launch project.",
                        status="planning",
                        priority="medium",
                        progress=0,
                        tags=[],
                    )
                )
                session.add(
                    ProjectExecution(
                        id=execution_id,
                        organization_id=org_id,
                        workspace_id=workspace_id,
                        project_id=project_id,
                        requested_by_id=user_id,
                        mode="full",
                        provider="policy",
                        status="queued",
                        stage="queued",
                        progress=0,
                        objective="Produce one isolated governed launch project.",
                        external_processing_confirmed=True,
                        budget_cap_usd=0.0 if access == "free" else 1.0,
                        result_summary={},
                        resource_class="project-build-cpu",
                        priority_rank=200,
                        attempts=0,
                        max_attempts=2,
                        review_status="not_requested",
                        rework_count=0,
                        version=1,
                    )
                )
                if access == "free":
                    policies[org_id] = ProjectAIProviderPolicy(
                        allowed_providers=frozenset({"ollama"}),
                        allowed_provider_models=frozenset({"ollama:gemma3:4b"}),
                        provider_scope_organization_id=platform_org_id,
                        offline_only=True,
                        privacy_mode=True,
                        max_total_estimated_cost_usd=0.0,
                    )
                elif access == "paid":
                    policies[org_id] = ProjectAIProviderPolicy(
                        allowed_providers=frozenset({"mistral"}),
                        allowed_provider_models=frozenset({"mistral:mistral-current-paid"}),
                        provider_scope_organization_id=platform_org_id,
                        max_total_estimated_cost_usd=1.0,
                    )
                else:
                    policies[org_id] = ProjectAIProviderPolicy(
                        allowed_providers=frozenset({"deepseek"}),
                        allowed_provider_models=frozenset({"deepseek:deepseek-current-paid"}),
                        provider_scope_organization_id=platform_org_id,
                        max_total_estimated_cost_usd=1.0,
                    )
            await session.commit()

        runner = DeterministicProjectAIIntegrationRunner(
            session_factory=SessionLocal,
            redis_url=str(__import__("os").environ["REDIS_URL"]),
            policy_resolver=lambda scope: policies[scope.organization_id],
            invokers={
                ("ollama", "gemma3:4b"): free_invoker,
                ("mistral", "mistral-current-paid"): paid_invoker,
                ("deepseek", "deepseek-current-paid"): override_invoker,
            },
            task_factory=_single_task,
            redis_key_prefix=f"aionex:test:p36c:launch100:{suffix}",
        )
        workers = [
            ProjectExecutionWorker(
                runner=runner,
                worker_id=f"launch100-worker-{suffix}-{index}",
                capacity=1,
            )
            for index in range(6)
        ]

        async def drain(worker: ProjectExecutionWorker) -> int:
            completed = 0
            while await worker.run_once():
                completed += 1
            return completed

        drained = await asyncio.gather(*(drain(worker) for worker in workers))
        elapsed = time.monotonic() - started
        assert sum(drained) == 100

        async with SessionLocal() as session:
            executions = list(
                (
                    await session.scalars(
                        select(ProjectExecution)
                        .where(ProjectExecution.id.in_(execution_ids))
                        .order_by(ProjectExecution.id)
                    )
                ).all()
            )
            assert len(executions) == 100
            assert all(row.status == "completed" for row in executions)
            assert all(row.attempts == 1 for row in executions)
            assert sum(row.provider == "ollama" for row in executions) == 50
            assert sum(row.provider == "mistral" for row in executions) == 40
            assert sum(row.provider == "deepseek" for row in executions) == 10
            assert await session.scalar(
                select(func.count(ProjectExecution.id)).where(
                    ProjectExecution.id.in_(execution_ids),
                    ProjectExecution.status.in_({"queued", "running"}),
                )
            ) == 0
            memories = list(
                (
                    await session.scalars(
                        select(ScopedMemory).where(ScopedMemory.scope_id.in_(project_ids))
                    )
                ).all()
            )
            assert len(memories) == 100
            assert len({(row.organization_id, row.scope_id) for row in memories}) == 100
            assert all(row.scope_type == "project" for row in memories)
            attempts = int(
                await session.scalar(
                    select(func.count(ProjectAIRouteAttemptRecord.id)).where(
                        ProjectAIRouteAttemptRecord.execution_id.in_(execution_ids)
                    )
                )
                or 0
            )
            assert attempts == 100
            completion_seconds = sorted(
                max(0.0, (row.completed_at - row.created_at).total_seconds())
                for row in executions
                if row.completed_at is not None and row.created_at is not None
            )
            assert len(completion_seconds) == 100
            p50 = statistics.median(completion_seconds)
            p95 = completion_seconds[94]
            max_seconds = completion_seconds[-1]
            # Completion timing is diagnostic evidence, not a functional SLA. Hosted CI
            # runner load can move this deterministic database-heavy test above the local
            # ~60s observation while admission, routing, isolation and bounded draining
            # remain correct. Keep the metrics visible without making wall-clock noise a
            # protected correctness gate.
            assert 0.0 <= p50 <= p95 <= max_seconds
            print(
                "LAUNCH100_ACCEPTANCE "
                f"users=100 workers=6 elapsed={elapsed:.3f}s "
                f"p50={p50:.3f}s p95={p95:.3f}s max={max_seconds:.3f}s "
                "free=50 paid=40 override=10"
            )

        assert len(free_invoker.calls) == 50
        assert len(paid_invoker.calls) == 40
        assert len(override_invoker.calls) == 10
    finally:
        async with SessionLocal() as session:
            # Consumer organization deletion cascades projects, executions, route evidence,
            # scoped memory and users. Delete the provider-pool organization last so no
            # restricted provider reference can survive cleanup.
            consumer_ids = list(
                (
                    await session.scalars(
                        select(Organization.id).where(Organization.id.like(f"{consumer_prefix}%"))
                    )
                ).all()
            )
            if consumer_ids:
                await session.execute(delete(Organization).where(Organization.id.in_(consumer_ids)))
                await session.flush()
            await session.execute(delete(Organization).where(Organization.id == platform_org_id))
            await session.commit()
