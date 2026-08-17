"""Phase 36C deterministic ProjectExecution integration foundation.

This module is deliberately not the production default runner.  It adapts the
protected durable routing authority to the existing synchronous Project Worker
runner contract using only explicitly injected provider invokers.  It also uses
organization/project-scoped ``ScopedMemory`` records and never falls back to the
legacy project-only SQLite memory store.

No provider credential is read here and no network call exists unless a caller
explicitly injects an invoker that performs one.  Production keeps
``ProjectPlanningRunner`` as the default until a later controlled rollout gate.
"""
from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as aioredis
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import (
    AuditEvent,
    Project,
    ProjectAIRoutePlanRecord,
    ProjectAIRouteTaskRecord,
    ProjectExecution,
    ScopedMemory,
    User,
)
from app.services.project_execution_routing import (
    ProjectAIProviderPolicy,
    ProjectAIScope,
    ProjectAITaskSpec,
)
from app.services.project_execution_routing_durable import (
    DurableProjectAIAuthority,
    DurableProjectAIRouteStore,
    ProjectAIBudgetExceeded,
    ProjectAIProviderCircuitOpen,
    ProjectAIProviderConcurrencyLimited,
    ProjectAIProviderRateLimited,
    ProjectAISharedCoordinator,
    usd_to_microusd,
)


class ProjectAIIntegrationError(RuntimeError):
    """The deterministic integrated Project AI cycle cannot continue safely."""


@dataclass(frozen=True, slots=True)
class ProjectAIInvocation:
    scope: ProjectAIScope
    task_id: str
    role: str
    task: str
    provider_id: str
    provider: str
    model: str
    prompt: str = field(repr=False)
    system_prompt: str = field(default="", repr=False)
    memory: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class ProjectAIInvocationResult:
    text: str = field(repr=False)
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    memory_note: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.cost_usd < 0 or self.latency_ms < 0:
            raise ValueError("provider result cost/latency must be non-negative")
        if self.input_tokens < 0 or self.output_tokens < 0:
            raise ValueError("provider result token counts must be non-negative")
        if self.memory_note is not None and len(self.memory_note) > 1000:
            raise ValueError("provider memory note exceeds the bounded memory limit")


class ProjectAIInvocationFailure(RuntimeError):
    def __init__(
        self,
        error_code: str,
        *,
        cost_usd: float = 0.0,
        latency_ms: float = 0.0,
    ) -> None:
        normalized = str(error_code or "").strip()
        if not normalized or len(normalized) > 120:
            raise ValueError("provider invocation error_code is invalid")
        if cost_usd < 0 or latency_ms < 0:
            raise ValueError("provider invocation failure cost/latency must be non-negative")
        super().__init__(normalized)
        self.error_code = normalized
        self.cost_usd = float(cost_usd)
        self.latency_ms = float(latency_ms)


ProjectAIInvoker = Callable[[ProjectAIInvocation], Awaitable[ProjectAIInvocationResult]]
ProjectAIPolicyResolver = Callable[[ProjectAIScope], ProjectAIProviderPolicy]
ProjectAITaskFactory = Callable[
    [str, str],
    tuple[ProjectAITaskSpec, ...],
]


def default_project_ai_tasks(
    project_name: str,
    objective: str,
) -> tuple[ProjectAITaskSpec, ...]:
    """Build a bounded four-role deterministic integration task graph."""

    normalized_project = str(project_name or "").strip()[:240]
    normalized_objective = str(objective or "").strip()[:6000]
    if len(normalized_project) < 2 or len(normalized_objective) < 10:
        raise ProjectAIIntegrationError("project name and objective are required")
    return (
        ProjectAITaskSpec(
            task_id="planner",
            role="planner",
            task="reasoning",
            prompt=f"Plan {normalized_project}: {normalized_objective}",
            max_tokens=1000,
        ),
        ProjectAITaskSpec(
            task_id="researcher",
            role="researcher",
            task="research",
            prompt=f"Research constraints for {normalized_project}: {normalized_objective}",
            max_tokens=1200,
        ),
        ProjectAITaskSpec(
            task_id="coder",
            role="coder",
            task="coding",
            prompt=f"Implement {normalized_project}: {normalized_objective}",
            max_tokens=1800,
            require_tools=True,
        ),
        ProjectAITaskSpec(
            task_id="reviewer",
            role="reviewer",
            task="review",
            prompt=f"Review {normalized_project}: {normalized_objective}",
            max_tokens=1000,
        ),
    )


class ProjectAIProjectMemoryAdapter:
    """Organization/project-scoped worker memory with prompt-free audit evidence."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def verify_scope(
        self,
        scope: ProjectAIScope,
        *,
        requested_by_id: str | None = None,
    ) -> ProjectExecution:
        async with self.session_factory() as session:
            execution = await session.scalar(
                select(ProjectExecution).where(
                    ProjectExecution.id == scope.execution_id,
                    ProjectExecution.organization_id == scope.organization_id,
                    ProjectExecution.workspace_id == scope.workspace_id,
                    ProjectExecution.project_id == scope.project_id,
                )
            )
            if execution is None:
                raise ProjectAIIntegrationError(
                    "Project AI memory scope does not match ProjectExecution"
                )
            project = await session.scalar(
                select(Project).where(
                    Project.id == scope.project_id,
                    Project.organization_id == scope.organization_id,
                    Project.workspace_id == scope.workspace_id,
                    Project.status != "deleted",
                )
            )
            if project is None:
                raise ProjectAIIntegrationError(
                    "Project AI memory project is outside the organization scope"
                )
            actor_id = requested_by_id or execution.requested_by_id
            actor = await session.scalar(
                select(User).where(
                    User.id == actor_id,
                    User.organization_id == scope.organization_id,
                    User.deleted_at.is_(None),
                )
            )
            if actor is None:
                raise ProjectAIIntegrationError(
                    "Project AI memory actor is outside the organization scope"
                )
            return execution

    async def recall(
        self,
        scope: ProjectAIScope,
        *,
        role: str | None = None,
        limit: int = 12,
    ) -> tuple[dict[str, Any], ...]:
        await self.verify_scope(scope)
        bounded_limit = max(1, min(int(limit), 50))
        now = datetime.now(UTC)
        async with self.session_factory() as session:
            statement = select(ScopedMemory).where(
                ScopedMemory.organization_id == scope.organization_id,
                ScopedMemory.scope_type == "project",
                ScopedMemory.scope_id == scope.project_id,
                ScopedMemory.status == "active",
                ScopedMemory.key.like("project-ai:%"),
                or_(ScopedMemory.expires_at.is_(None), ScopedMemory.expires_at > now),
            )
            rows = list(
                (
                    await session.scalars(
                        statement.order_by(ScopedMemory.updated_at.desc()).limit(
                            bounded_limit
                        )
                    )
                ).all()
            )
        values = []
        normalized_role = str(role or "").strip().lower()
        for row in rows:
            value = dict(row.value or {})
            if normalized_role and str(value.get("role") or "").lower() != normalized_role:
                continue
            values.append(value)
        return tuple(values)

    async def remember_success(
        self,
        scope: ProjectAIScope,
        *,
        requested_by_id: str,
        task_id: str,
        role: str,
        provider_id: str,
        provider: str,
        model: str,
        evidence_ref: str,
        result: ProjectAIInvocationResult,
    ) -> ScopedMemory:
        await self.verify_scope(scope, requested_by_id=requested_by_id)
        task_id = str(task_id or "").strip()
        role = str(role or "").strip().lower()
        if not task_id or not role:
            raise ProjectAIIntegrationError("Project AI memory task/role is required")
        memory_note = (result.memory_note or "").strip() or None
        fingerprint = hashlib.sha256(
            f"{scope.execution_id}\0{task_id}\0{role}".encode("utf-8")
        ).hexdigest()[:24]
        memory_key = f"project-ai:{role}:{fingerprint}"
        value = {
            "schema_version": 1,
            "execution_id": scope.execution_id,
            "task_id": task_id,
            "role": role,
            "provider_id": provider_id,
            "provider": provider,
            "model": model,
            "evidence_ref": evidence_ref,
            "outcome": "success",
            "actual_microusd": usd_to_microusd(result.cost_usd),
            "latency_ms": float(result.latency_ms),
            "result_sha256": hashlib.sha256(result.text.encode("utf-8")).hexdigest(),
            "memory_note": memory_note,
        }
        async with self.session_factory() as session:
            async with session.begin():
                item = await session.scalar(
                    select(ScopedMemory)
                    .where(
                        ScopedMemory.organization_id == scope.organization_id,
                        ScopedMemory.scope_type == "project",
                        ScopedMemory.scope_id == scope.project_id,
                        ScopedMemory.key == memory_key,
                    )
                    .with_for_update()
                )
                if item is None:
                    item = ScopedMemory(
                        id=str(__import__("uuid").uuid4()),
                        organization_id=scope.organization_id,
                        created_by_id=requested_by_id,
                        scope_type="project",
                        scope_id=scope.project_id,
                        key=memory_key,
                        version=1,
                    )
                    session.add(item)
                else:
                    item.version += 1
                item.value = value
                item.summary = memory_note
                item.confidence = 1.0
                item.status = "active"
                item.revoked_at = None
                session.add(
                    AuditEvent(
                        organization_id=scope.organization_id,
                        user_id=requested_by_id,
                        action="project.ai.memory.upserted",
                        resource_type="scoped_memory",
                        resource_id=item.id,
                        details={
                            "project_id": scope.project_id,
                            "execution_id": scope.execution_id,
                            "task_id": task_id,
                            "role": role,
                            "provider_id": provider_id,
                            "provider": provider,
                            "model": model,
                            "evidence_ref": evidence_ref,
                            "memory_key": memory_key,
                            "version": item.version,
                        },
                    )
                )
            return item


class DeterministicProjectAIIntegrationRunner:
    """Test/integration-only runner compatible with ``ProjectExecutionWorker``."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        redis_url: str,
        policy_resolver: ProjectAIPolicyResolver,
        invokers: Mapping[tuple[str, str], ProjectAIInvoker],
        task_factory: ProjectAITaskFactory = default_project_ai_tasks,
        redis_key_prefix: str = "aionex:project-ai:integration:v1",
    ) -> None:
        self.session_factory = session_factory
        self.redis_url = str(redis_url or "").strip()
        self.policy_resolver = policy_resolver
        self.invokers = dict(invokers)
        self.task_factory = task_factory
        self.redis_key_prefix = str(redis_key_prefix or "").strip()
        if not self.redis_url or not self.redis_key_prefix:
            raise ValueError("deterministic Project AI Redis configuration is required")
        if not self.invokers:
            raise ValueError("at least one deterministic Project AI invoker is required")

    def run(
        self,
        *,
        job_id: str,
        project_name: str,
        objective: str,
        tenant_id: str = "platform",
        requested_by_id: str = "system",
        execution_mode: str = "full",
        project_id: str | None = None,
        three_d_asset_manifest: str | None = None,
        stage_callback: Callable[[str, int], None] | None = None,
    ) -> dict[str, Any]:
        if three_d_asset_manifest:
            raise ProjectAIIntegrationError(
                "deterministic Project AI integration does not handle 3D asset staging"
            )
        if execution_mode not in {"full", "planning"}:
            raise ProjectAIIntegrationError(
                "deterministic Project AI integration supports planning/full only"
            )
        return asyncio.run(
            self._run_async(
                job_id=job_id,
                project_name=project_name,
                objective=objective,
                tenant_id=tenant_id,
                requested_by_id=requested_by_id,
                execution_mode=execution_mode,
                project_id=project_id,
                stage_callback=stage_callback,
            )
        )

    async def _run_async(
        self,
        *,
        job_id: str,
        project_name: str,
        objective: str,
        tenant_id: str,
        requested_by_id: str,
        execution_mode: str,
        project_id: str | None,
        stage_callback: Callable[[str, int], None] | None,
    ) -> dict[str, Any]:
        def stage(name: str, progress: int) -> None:
            if stage_callback is not None:
                stage_callback(name, max(0, min(100, int(progress))))

        scope = await self._load_scope(
            job_id=job_id,
            tenant_id=tenant_id,
            requested_by_id=requested_by_id,
            project_id=project_id,
        )
        tasks = self.task_factory(project_name, objective)
        if not tasks:
            raise ProjectAIIntegrationError("deterministic Project AI task graph is empty")
        policy = self.policy_resolver(scope)
        memory = ProjectAIProjectMemoryAdapter(self.session_factory)
        await memory.verify_scope(scope, requested_by_id=requested_by_id)

        stage("ai_route_plan", 12)
        async with self.session_factory() as session:
            plan_record = await DurableProjectAIRouteStore(session).create_plan(
                scope, tasks, policy
            )
            await session.commit()
            plan_id = plan_record.id

        redis_client = aioredis.from_url(
            self.redis_url,
            decode_responses=True,
            max_connections=16,
        )
        coordinator = ProjectAISharedCoordinator(
            redis_client, key_prefix=self.redis_key_prefix
        )
        authority = DurableProjectAIAuthority(self.session_factory, coordinator)
        results: list[dict[str, Any]] = []
        requests_count = 0
        retries_count = 0
        input_tokens = 0
        output_tokens = 0
        total_cost = 0.0
        try:
            route_rows = await self._task_routes(plan_id)
            route_by_task = {row.task_id: row for row in route_rows}
            for index, spec in enumerate(tasks):
                route = route_by_task.get(spec.task_id)
                if route is None:
                    raise ProjectAIIntegrationError(
                        f"durable route is missing for task {spec.task_id}"
                    )
                remembered = await memory.recall(scope, limit=12)
                selected: dict[str, Any] | None = None
                failures: list[dict[str, Any]] = []
                for candidate_index in range(len(route.candidates)):
                    try:
                        permit = await authority.begin_attempt(
                            scope,
                            task_id=spec.task_id,
                            candidate_index=candidate_index,
                        )
                    except (
                        ProjectAIProviderRateLimited,
                        ProjectAIProviderConcurrencyLimited,
                        ProjectAIProviderCircuitOpen,
                        ProjectAIBudgetExceeded,
                    ) as exc:
                        failures.append(
                            {
                                "candidate_index": candidate_index,
                                "error_code": type(exc).__name__,
                            }
                        )
                        if candidate_index + 1 < len(route.candidates):
                            retries_count += 1
                            continue
                        raise ProjectAIIntegrationError(
                            f"no approved route is currently available for task {spec.task_id}"
                        ) from exc

                    invoker = self.invokers.get((permit.provider_type, permit.model))
                    requests_count += 1
                    invocation = ProjectAIInvocation(
                        scope=scope,
                        task_id=spec.task_id,
                        role=spec.role,
                        task=spec.task,
                        provider_id=permit.provider_id,
                        provider=permit.provider_type,
                        model=permit.model,
                        prompt=spec.prompt,
                        system_prompt=spec.system_prompt,
                        memory=remembered,
                    )
                    if invoker is None:
                        failure = ProjectAIInvocationFailure(
                            "provider_adapter_unavailable"
                        )
                    else:
                        try:
                            response = await invoker(invocation)
                        except ProjectAIInvocationFailure as exc:
                            failure = exc
                        except Exception:
                            failure = ProjectAIInvocationFailure("provider_transport")
                        else:
                            await authority.finish_attempt(
                                permit,
                                success=True,
                                actual_cost_usd=response.cost_usd,
                                latency_ms=response.latency_ms,
                            )
                            await memory.remember_success(
                                scope,
                                requested_by_id=requested_by_id,
                                task_id=spec.task_id,
                                role=spec.role,
                                provider_id=permit.provider_id,
                                provider=permit.provider_type,
                                model=permit.model,
                                evidence_ref=(
                                    str(route.candidates[candidate_index].get("evidence_ref") or "")
                                ),
                                result=response,
                            )
                            total_cost += response.cost_usd
                            input_tokens += response.input_tokens
                            output_tokens += response.output_tokens
                            selected = {
                                "task_id": spec.task_id,
                                "role": spec.role,
                                "provider": permit.provider_type,
                                "model": permit.model,
                                "fallback_used": candidate_index > 0,
                                "candidate_index": candidate_index,
                                "evidence_ref": str(
                                    route.candidates[candidate_index].get("evidence_ref")
                                    or ""
                                ),
                                "cost_usd": response.cost_usd,
                                "latency_ms": response.latency_ms,
                                "memory_items_seen": len(remembered),
                                "result_sha256": hashlib.sha256(
                                    response.text.encode("utf-8")
                                ).hexdigest(),
                            }
                            break

                    await authority.finish_attempt(
                        permit,
                        success=False,
                        actual_cost_usd=failure.cost_usd,
                        latency_ms=failure.latency_ms,
                        error_code=failure.error_code,
                    )
                    total_cost += failure.cost_usd
                    failures.append(
                        {
                            "candidate_index": candidate_index,
                            "provider": permit.provider_type,
                            "model": permit.model,
                            "error_code": failure.error_code,
                        }
                    )
                    if candidate_index + 1 < len(route.candidates):
                        retries_count += 1
                        continue
                    raise ProjectAIIntegrationError(
                        f"all approved provider routes failed for task {spec.task_id}"
                    )
                if selected is None:
                    raise ProjectAIIntegrationError(
                        f"Project AI task {spec.task_id} did not produce a result"
                    )
                selected["prior_failures"] = failures
                results.append(selected)
                stage(
                    f"ai_{spec.role}_completed",
                    20 + round(((index + 1) / len(tasks)) * 70),
                )
        finally:
            closer = getattr(redis_client, "aclose", None) or redis_client.close
            await closer()

        providers = sorted({item["provider"] for item in results})
        final = results[-1]
        stage("ai_integration_complete", 96)
        return {
            "success": True,
            "phase": 36,
            "mode": execution_mode,
            "provider": providers[0] if len(providers) == 1 else "multi-provider",
            "model": final["model"],
            "requests_count": requests_count,
            "retries_count": retries_count,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "calculated_cost": round(total_cost, 8),
            "approved": True,
            "readiness_score": 1.0,
            "workforce": [],
            "provider_plan": results,
            "integration_foundation": True,
            "all_governance_layers_executed": False,
            "model_claims_used_as_execution_proof": False,
            "production_modified": False,
        }

    async def _load_scope(
        self,
        *,
        job_id: str,
        tenant_id: str,
        requested_by_id: str,
        project_id: str | None,
    ) -> ProjectAIScope:
        async with self.session_factory() as session:
            execution = await session.get(ProjectExecution, job_id)
            if execution is None:
                raise ProjectAIIntegrationError("ProjectExecution was not found")
            if (
                execution.organization_id != tenant_id
                or execution.requested_by_id != requested_by_id
                or execution.project_id != project_id
            ):
                raise ProjectAIIntegrationError(
                    "deterministic Project AI runner payload is outside execution scope"
                )
            return ProjectAIScope(
                organization_id=execution.organization_id,
                workspace_id=execution.workspace_id,
                project_id=execution.project_id,
                execution_id=execution.id,
            )

    async def _task_routes(
        self,
        plan_id: str,
    ) -> tuple[ProjectAIRouteTaskRecord, ...]:
        async with self.session_factory() as session:
            rows = list(
                (
                    await session.scalars(
                        select(ProjectAIRouteTaskRecord)
                        .where(ProjectAIRouteTaskRecord.plan_id == plan_id)
                        .order_by(ProjectAIRouteTaskRecord.created_at.asc())
                    )
                ).all()
            )
            plan = await session.get(ProjectAIRoutePlanRecord, plan_id)
            if plan is None:
                raise ProjectAIIntegrationError("durable Project AI route plan disappeared")
            return tuple(rows)
