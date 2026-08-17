"""Phase 36C durable multi-worker provider routing authority contracts."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import os
from uuid import uuid4

import pytest
import redis.asyncio as aioredis
from redis.exceptions import RedisError
from sqlalchemy import delete, func, select

from aios.providers import DataSensitivity
from app.db.base import Base, SessionLocal
from app.db.models import (
    AIProvider,
    AuditEvent,
    Organization,
    Project,
    ProjectAIExecutionBudget,
    ProjectAIRouteAttemptRecord,
    ProjectAIRoutePlanRecord,
    ProjectAIRouteTaskRecord,
    ProjectExecution,
    User,
    Workspace,
)
from app.services.project_execution_routing import (
    ProjectAIProviderPolicy,
    ProjectAIScope,
    ProjectAITaskSpec,
)
from app.services.project_execution_routing_durable import (
    DurableProjectAIAuthority,
    DurableProjectAIResolver,
    DurableProjectAIRouteStore,
    ProjectAIBudgetExceeded,
    ProjectAIDurableRoutingError,
    ProjectAIProviderCircuitOpen,
    ProjectAIProviderConcurrencyLimited,
    ProjectAIProviderLimits,
    ProjectAIProviderRateLimited,
    ProjectAISharedCoordinationError,
    ProjectAISharedCoordinator,
)


def _validated_model(
    model: str,
    *,
    tasks: tuple[str, ...] = ("coding",),
    local: bool = False,
    output_cost_per_million: float = 10.0,
    requests_per_minute: int = 100,
    concurrent_requests: int = 2,
    failure_threshold: int = 3,
    expires_delta: timedelta = timedelta(days=1),
) -> dict[str, object]:
    now = datetime.now(UTC)
    return {
        "model": model,
        "tasks": list(tasks),
        "evidence_ref": f"phase36c:test:{model}",
        "validated_at": (now - timedelta(minutes=5)).isoformat(),
        "expires_at": (now + expires_delta).isoformat(),
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
        "output_cost_per_million": output_cost_per_million,
        "requests_per_minute": requests_per_minute,
        "concurrent_requests": concurrent_requests,
        "circuit_failure_threshold": failure_threshold,
        "circuit_failure_window_seconds": 60,
        "circuit_open_seconds": 60,
        "lease_seconds": 30,
    }


async def _seed_scope(
    suffix: str,
    *,
    budget_cap_usd: float = 1.0,
    providers: tuple[tuple[str, str, dict[str, object], str], ...] = (),
) -> tuple[ProjectAIScope, str, tuple[AIProvider, ...]]:
    org = Organization(
        id=f"p36c-org-{suffix}",
        name=f"Phase 36C {suffix}",
        slug=f"p36c-org-{suffix}",
        plan="enterprise",
        status="active",
    )
    user = User(
        id=f"p36c-user-{suffix}",
        organization_id=org.id,
        role_id=None,
        email=f"p36c-{suffix}@example.com",
        name="Phase 36C Operator",
        password_hash="unused",
        status="active",
    )
    workspace = Workspace(
        id=f"p36c-ws-{suffix}",
        organization_id=org.id,
        name="Phase 36C Workspace",
        slug=f"p36c-ws-{suffix}",
        status="active",
    )
    project = Project(
        id=f"p36c-project-{suffix}",
        organization_id=org.id,
        workspace_id=workspace.id,
        owner_id=user.id,
        name="Durable Multi Provider Project",
        slug=f"p36c-project-{suffix}",
        description="Exercise tenant-safe durable Project AI routing.",
        status="planning",
        priority="high",
        progress=0,
        tags=["phase36c"],
    )
    execution = ProjectExecution(
        id=f"p36c-exec-{suffix}",
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
        max_attempts=3,
    )
    provider_rows = tuple(
        AIProvider(
            id=f"p36c-provider-{provider_type}-{suffix}-{index}",
            organization_id=org.id,
            name=f"{provider_type} {suffix}",
            type=provider_type,
            status=status,
            encrypted_api_key=None,
            base_url=None,
            config={"enabled": True, "validated_models": [model_config]},
        )
        for index, (provider_type, _model, model_config, status) in enumerate(providers)
    )
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
        provider_rows,
    )


async def _cleanup_org(organization_id: str) -> None:
    async with SessionLocal() as session:
        await session.execute(
            delete(AuditEvent).where(AuditEvent.organization_id == organization_id)
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


async def _redis_client():
    return aioredis.from_url(os.environ["REDIS_URL"], decode_responses=True)


async def _close_redis(client) -> None:
    closer = getattr(client, "aclose", None) or client.close
    await closer()


def _task(
    task_id: str,
    *,
    prompt: str = "secret project prompt",
    max_tokens: int = 100,
    allow_failover: bool = True,
    max_fallbacks: int = 1,
    priority: tuple[str, ...] = ("openai", "anthropic"),
    sensitivity: DataSensitivity = DataSensitivity.INTERNAL,
    require_local: bool = False,
) -> ProjectAITaskSpec:
    return ProjectAITaskSpec(
        task_id=task_id,
        role="coder",
        task="coding",
        prompt=prompt,
        max_tokens=max_tokens,
        allow_failover=allow_failover,
        max_fallbacks=max_fallbacks,
        provider_priority=priority,
        sensitivity=sensitivity,
        require_local=require_local,
    )


def test_phase36c_durable_schema_contract() -> None:
    plans = Base.metadata.tables["project_ai_route_plans"]
    tasks = Base.metadata.tables["project_ai_route_tasks"]
    attempts = Base.metadata.tables["project_ai_route_attempts"]
    budgets = Base.metadata.tables["project_ai_execution_budgets"]
    assert {"organization_id", "project_id", "execution_id", "evidence"} <= set(plans.c.keys())
    assert {"primary_provider_id", "candidates", "selected_provider_id"} <= set(tasks.c.keys())
    assert {"provider_id", "reserved_microusd", "actual_microusd"} <= set(attempts.c.keys())
    assert {"limit_microusd", "reserved_microusd", "spent_microusd"} <= set(budgets.c.keys())


@pytest.mark.asyncio
async def test_resolver_is_tenant_scoped_connected_and_requires_current_explicit_models() -> None:
    suffix = uuid4().hex[:8]
    other_suffix = uuid4().hex[:8]
    model = _validated_model("gpt-live-1")
    scope, org_id, providers = await _seed_scope(
        suffix,
        providers=(
            ("openai", "gpt-live-1", model, "connected"),
            ("anthropic", "claude-configured", _validated_model("claude-configured"), "configured"),
        ),
    )
    _, other_org_id, _ = await _seed_scope(
        other_suffix,
        providers=(("openai", "gpt-other", _validated_model("gpt-other"), "connected"),),
    )
    try:
        async with SessionLocal() as session:
            resolved = await DurableProjectAIResolver(session).resolve(
                scope,
                ProjectAIProviderPolicy(allowed_providers=frozenset({"openai", "anthropic"})),
            )
            assert [(item.provider_type, item.route_model.model) for item in resolved] == [
                ("openai", "gpt-live-1")
            ]
            assert resolved[0].provider_id == providers[0].id
            bad_scope = ProjectAIScope(
                organization_id=other_org_id,
                workspace_id=scope.workspace_id,
                project_id=scope.project_id,
                execution_id=scope.execution_id,
            )
            with pytest.raises(ProjectAIDurableRoutingError, match="scope does not match"):
                await DurableProjectAIResolver(session).resolve(
                    bad_scope,
                    ProjectAIProviderPolicy(allowed_providers=frozenset({"openai"})),
                )
    finally:
        await _cleanup_org(org_id)
        await _cleanup_org(other_org_id)


@pytest.mark.asyncio
async def test_resolver_rejects_default_alias_and_ignores_expired_evidence() -> None:
    suffix = uuid4().hex[:8]
    scope, org_id, _ = await _seed_scope(
        suffix,
        providers=(("openai", "default", _validated_model("default"), "connected"),),
    )
    try:
        async with SessionLocal() as session:
            with pytest.raises(ProjectAIDurableRoutingError, match="default model aliases"):
                await DurableProjectAIResolver(session).resolve(
                    scope,
                    ProjectAIProviderPolicy(allowed_providers=frozenset({"openai"})),
                )
            provider = await session.scalar(
                select(AIProvider).where(AIProvider.organization_id == org_id)
            )
            assert provider is not None
            provider.config = {
                "enabled": True,
                "validated_models": [
                    _validated_model("expired-model", expires_delta=timedelta(seconds=-1))
                ],
            }
            await session.commit()
        async with SessionLocal() as session:
            with pytest.raises(ProjectAIDurableRoutingError, match="no connected tenant provider"):
                await DurableProjectAIResolver(session).resolve(
                    scope,
                    ProjectAIProviderPolicy(allowed_providers=frozenset({"openai"})),
                )
    finally:
        await _cleanup_org(org_id)


@pytest.mark.asyncio
async def test_route_plan_persistence_is_prompt_free_and_idempotent() -> None:
    suffix = uuid4().hex[:8]
    secret_prompt = "PRIVATE-PROMPT-MUST-NOT-BE-PERSISTED"
    scope, org_id, _ = await _seed_scope(
        suffix,
        providers=(
            ("openai", "gpt-live-1", _validated_model("gpt-live-1"), "connected"),
            ("anthropic", "claude-live-1", _validated_model("claude-live-1"), "connected"),
        ),
    )
    policy = ProjectAIProviderPolicy(
        allowed_providers=frozenset({"openai", "anthropic"})
    )
    tasks = (_task("code", prompt=secret_prompt),)
    try:
        async with SessionLocal() as session:
            store = DurableProjectAIRouteStore(session)
            first = await store.create_plan(scope, tasks, policy)
            await session.commit()
            first_id = first.id
        async with SessionLocal() as session:
            second = await DurableProjectAIRouteStore(session).create_plan(
                scope, tasks, policy
            )
            assert second.id == first_id
            route_tasks = list(
                (
                    await session.scalars(
                        select(ProjectAIRouteTaskRecord).where(
                            ProjectAIRouteTaskRecord.plan_id == first_id
                        )
                    )
                ).all()
            )
            audits = list(
                (
                    await session.scalars(
                        select(AuditEvent).where(
                            AuditEvent.organization_id == org_id,
                            AuditEvent.action == "project.ai.route_plan.created",
                        )
                    )
                ).all()
            )
            budget = await session.get(ProjectAIExecutionBudget, scope.execution_id)
            assert len(route_tasks) == 1
            assert len(route_tasks[0].candidates) == 2
            assert budget is not None and budget.limit_microusd == 1_000_000
            assert len(audits) == 1
            persisted = json.dumps(
                {
                    "plan": second.evidence,
                    "policy": second.policy,
                    "tasks": [item.candidates for item in route_tasks],
                    "audit": [item.details for item in audits],
                },
                sort_keys=True,
            )
            assert secret_prompt not in persisted
            assert "gpt-live-1" in persisted
            assert "claude-live-1" in persisted
            assert "default" not in persisted
    finally:
        await _cleanup_org(org_id)


@pytest.mark.asyncio
async def test_shared_redis_coordination_enforces_concurrency_rate_and_circuit_across_instances() -> None:
    prefix = f"aionex:test:p36c:{uuid4().hex}"
    client_a = await _redis_client()
    client_b = await _redis_client()
    coordinator_a = ProjectAISharedCoordinator(client_a, key_prefix=prefix)
    coordinator_b = ProjectAISharedCoordinator(client_b, key_prefix=prefix)
    limits = ProjectAIProviderLimits(
        requests_per_minute=10,
        concurrent_requests=1,
        circuit_failure_threshold=2,
        circuit_failure_window_seconds=60,
        circuit_open_seconds=60,
        lease_seconds=30,
    )
    try:
        lease = await coordinator_a.acquire(
            organization_id="org-a",
            provider_id="provider-a",
            model="model-a",
            limits=limits,
        )
        with pytest.raises(ProjectAIProviderConcurrencyLimited):
            await coordinator_b.acquire(
                organization_id="org-a",
                provider_id="provider-a",
                model="model-a",
                limits=limits,
            )
        assert await coordinator_a.release(lease) is True

        first_failure = await coordinator_a.acquire(
            organization_id="org-a",
            provider_id="provider-a",
            model="model-a",
            limits=limits,
        )
        assert await coordinator_a.record_failure(first_failure, event_id="attempt-1") == 1
        assert await coordinator_a.record_failure(first_failure, event_id="attempt-1") == 1
        await coordinator_a.release(first_failure)
        second_failure = await coordinator_b.acquire(
            organization_id="org-a",
            provider_id="provider-a",
            model="model-a",
            limits=limits,
        )
        assert await coordinator_b.record_failure(second_failure, event_id="attempt-2") == 2
        await coordinator_b.release(second_failure)
        with pytest.raises(ProjectAIProviderCircuitOpen):
            await coordinator_a.acquire(
                organization_id="org-a",
                provider_id="provider-a",
                model="model-a",
                limits=limits,
            )

        rate_limits = ProjectAIProviderLimits(
            requests_per_minute=2,
            concurrent_requests=5,
            circuit_failure_threshold=5,
            circuit_failure_window_seconds=60,
            circuit_open_seconds=60,
            lease_seconds=30,
        )
        for _ in range(2):
            item = await coordinator_a.acquire(
                organization_id="org-a",
                provider_id="provider-rate",
                model="model-rate",
                limits=rate_limits,
            )
            await coordinator_a.release(item)
        with pytest.raises(ProjectAIProviderRateLimited):
            await coordinator_b.acquire(
                organization_id="org-a",
                provider_id="provider-rate",
                model="model-rate",
                limits=rate_limits,
            )
    finally:
        await _close_redis(client_a)
        await _close_redis(client_b)


@pytest.mark.asyncio
async def test_shared_coordination_keys_are_hashed_and_redis_failure_is_fail_closed() -> None:
    prefix = f"aionex:test:p36c:opaque:{uuid4().hex}"
    client = await _redis_client()
    coordinator = ProjectAISharedCoordinator(client, key_prefix=prefix)
    limits = ProjectAIProviderLimits(
        requests_per_minute=10,
        concurrent_requests=2,
        circuit_failure_threshold=2,
        circuit_failure_window_seconds=60,
        circuit_open_seconds=60,
        lease_seconds=30,
    )
    organization_id = "org-sensitive-id"
    provider_id = "provider-sensitive-id"
    model = "model-sensitive-id"
    try:
        lease = await coordinator.acquire(
            organization_id=organization_id,
            provider_id=provider_id,
            model=model,
            limits=limits,
        )
        keys = [str(item) async for item in client.scan_iter(match=f"{prefix}:*")]
        assert keys
        rendered = "\n".join(keys)
        assert organization_id not in rendered
        assert provider_id not in rendered
        assert model not in rendered
        assert lease.digest in rendered
        await coordinator.release(lease)
    finally:
        await _close_redis(client)

    class BrokenRedis:
        async def eval(self, *_args, **_kwargs):
            raise RedisError("unavailable")

    broken = ProjectAISharedCoordinator(BrokenRedis(), key_prefix=prefix)
    with pytest.raises(ProjectAISharedCoordinationError, match="unavailable"):
        await broken.acquire(
            organization_id=organization_id,
            provider_id=provider_id,
            model=model,
            limits=limits,
        )


@pytest.mark.asyncio
async def test_durable_authorities_share_concurrency_budget_and_idempotent_finalization() -> None:
    suffix = uuid4().hex[:8]
    scope, org_id, _ = await _seed_scope(
        suffix,
        budget_cap_usd=1.0,
        providers=((
            "openai",
            "gpt-live-1",
            _validated_model("gpt-live-1", concurrent_requests=1),
            "connected",
        ),),
    )
    policy = ProjectAIProviderPolicy(allowed_providers=frozenset({"openai"}))
    tasks = (
        _task("code-a", allow_failover=False, max_fallbacks=0, priority=("openai",)),
        _task("code-b", allow_failover=False, max_fallbacks=0, priority=("openai",)),
    )
    prefix = f"aionex:test:p36c:authority:{uuid4().hex}"
    client_a = await _redis_client()
    client_b = await _redis_client()
    try:
        async with SessionLocal() as session:
            await DurableProjectAIRouteStore(session).create_plan(scope, tasks, policy)
            await session.commit()
        authority_a = DurableProjectAIAuthority(
            SessionLocal, ProjectAISharedCoordinator(client_a, key_prefix=prefix)
        )
        authority_b = DurableProjectAIAuthority(
            SessionLocal, ProjectAISharedCoordinator(client_b, key_prefix=prefix)
        )
        permit_a = await authority_a.begin_attempt(scope, task_id="code-a", candidate_index=0)
        with pytest.raises(ProjectAIProviderConcurrencyLimited):
            await authority_b.begin_attempt(scope, task_id="code-b", candidate_index=0)
        await authority_a.finish_attempt(
            permit_a,
            success=True,
            actual_cost_usd=0.0005,
            latency_ms=20.0,
        )
        permit_b = await authority_b.begin_attempt(scope, task_id="code-b", candidate_index=0)
        await authority_b.finish_attempt(
            permit_b,
            success=True,
            actual_cost_usd=0.0004,
            latency_ms=15.0,
        )
        # Retrying the same finalization must not double-spend or double-count shared state.
        await authority_b.finish_attempt(
            permit_b,
            success=True,
            actual_cost_usd=0.0004,
            latency_ms=15.0,
        )
        async with SessionLocal() as session:
            budget = await session.get(ProjectAIExecutionBudget, scope.execution_id)
            attempts = int(
                await session.scalar(
                    select(func.count(ProjectAIRouteAttemptRecord.id)).where(
                        ProjectAIRouteAttemptRecord.organization_id == org_id
                    )
                )
                or 0
            )
            completed = int(
                await session.scalar(
                    select(func.count(ProjectAIRouteTaskRecord.id)).where(
                        ProjectAIRouteTaskRecord.organization_id == org_id,
                        ProjectAIRouteTaskRecord.status == "completed",
                    )
                )
                or 0
            )
            plan = await session.scalar(
                select(ProjectAIRoutePlanRecord).where(
                    ProjectAIRoutePlanRecord.organization_id == org_id
                )
            )
            assert budget is not None
            assert budget.reserved_microusd == 0
            assert budget.spent_microusd == 900
            assert attempts == 2
            assert completed == 2
            assert plan is not None and plan.status == "completed"
    finally:
        await _close_redis(client_a)
        await _close_redis(client_b)
        await _cleanup_org(org_id)


@pytest.mark.asyncio
async def test_failed_primary_spend_can_block_fallback_before_provider_execution() -> None:
    suffix = uuid4().hex[:8]
    scope, org_id, _ = await _seed_scope(
        suffix,
        budget_cap_usd=0.0015,
        providers=(
            ("openai", "gpt-live-1", _validated_model("gpt-live-1"), "connected"),
            ("anthropic", "claude-live-1", _validated_model("claude-live-1"), "connected"),
        ),
    )
    policy = ProjectAIProviderPolicy(
        allowed_providers=frozenset({"openai", "anthropic"})
    )
    tasks = (_task("code", priority=("openai", "anthropic")),)
    prefix = f"aionex:test:p36c:budget:{uuid4().hex}"
    client = await _redis_client()
    try:
        async with SessionLocal() as session:
            plan = await DurableProjectAIRouteStore(session).create_plan(scope, tasks, policy)
            assert plan.total_primary_estimated_microusd < 1500
            await session.commit()
        authority = DurableProjectAIAuthority(
            SessionLocal, ProjectAISharedCoordinator(client, key_prefix=prefix)
        )
        primary = await authority.begin_attempt(scope, task_id="code", candidate_index=0)
        await authority.finish_attempt(
            primary,
            success=False,
            actual_cost_usd=0.0008,
            latency_ms=40.0,
            error_code="provider_transport",
        )
        with pytest.raises(ProjectAIBudgetExceeded):
            await authority.begin_attempt(scope, task_id="code", candidate_index=1)
        async with SessionLocal() as session:
            budget = await session.get(ProjectAIExecutionBudget, scope.execution_id)
            attempts = int(
                await session.scalar(
                    select(func.count(ProjectAIRouteAttemptRecord.id)).where(
                        ProjectAIRouteAttemptRecord.organization_id == org_id
                    )
                )
                or 0
            )
            assert budget is not None
            assert budget.spent_microusd == 800
            assert budget.reserved_microusd == 0
            assert attempts == 1
    finally:
        await _close_redis(client)
        await _cleanup_org(org_id)
