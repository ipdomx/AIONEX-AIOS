"""Phase 36C durable tenant-safe Project AI routing authority.

This layer deliberately does not execute provider HTTP calls or read provider
credentials.  It resolves only organization-owned, connected AIProvider rows with
explicit non-placeholder ``validated_models`` evidence, persists prompt-free route
plans/attempts/audit data in PostgreSQL, coordinates shared provider rate/concurrency
and circuit state through Redis, and reserves project AI budget in integer micro-USD.

Live ProjectExecution wiring is a later Phase 36C gate.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP
from typing import Any
from uuid import uuid4

from redis.exceptions import RedisError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import (
    AIProvider,
    AuditEvent,
    ProjectAIExecutionBudget,
    ProjectAIRouteAttemptRecord,
    ProjectAIRoutePlanRecord,
    ProjectAIRouteTaskRecord,
    ProjectExecution,
)
from app.services.project_execution_routing import (
    ProjectAIProviderPolicy,
    ProjectAIRoutePlan,
    ProjectAIRoutePlanner,
    ProjectAIRoutingError,
    ProjectAIScope,
    ProjectAITaskSpec,
    ValidatedProviderModel,
)


class ProjectAIDurableRoutingError(ProjectAIRoutingError):
    """Durable Project AI routing state cannot be proven safely."""


class ProjectAISharedCoordinationError(ProjectAIDurableRoutingError):
    """Shared provider coordination failed closed."""


class ProjectAIProviderRateLimited(ProjectAISharedCoordinationError):
    """The shared provider request window is exhausted."""


class ProjectAIProviderConcurrencyLimited(ProjectAISharedCoordinationError):
    """The shared provider concurrent-request limit is exhausted."""


class ProjectAIProviderCircuitOpen(ProjectAISharedCoordinationError):
    """The shared provider/model circuit breaker is open."""


class ProjectAIBudgetExceeded(ProjectAIDurableRoutingError):
    """The durable execution budget cannot reserve another provider attempt."""


_MICRO_USD = Decimal("1000000")


def usd_to_microusd(value: float, *, reserve: bool = False) -> int:
    amount = Decimal(str(value))
    if not amount.is_finite() or amount < 0:
        raise ValueError("USD amount must be finite and non-negative")
    rounding = ROUND_CEILING if reserve else ROUND_HALF_UP
    return int((amount * _MICRO_USD).to_integral_value(rounding=rounding))


def _required(value: Any, label: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ProjectAIDurableRoutingError(f"{label} is required")
    return normalized


def _utc(value: Any, label: str) -> datetime:
    raw = _required(value, label)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProjectAIDurableRoutingError(f"{label} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ProjectAIDurableRoutingError(f"{label} must include a timezone")
    return parsed.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class ProjectAIProviderLimits:
    requests_per_minute: int
    concurrent_requests: int
    circuit_failure_threshold: int
    circuit_failure_window_seconds: int
    circuit_open_seconds: int
    lease_seconds: int = 120

    def __post_init__(self) -> None:
        for name, value, minimum, maximum in (
            ("requests_per_minute", self.requests_per_minute, 1, 100000),
            ("concurrent_requests", self.concurrent_requests, 1, 10000),
            ("circuit_failure_threshold", self.circuit_failure_threshold, 1, 1000),
            ("circuit_failure_window_seconds", self.circuit_failure_window_seconds, 1, 86400),
            ("circuit_open_seconds", self.circuit_open_seconds, 1, 86400),
            ("lease_seconds", self.lease_seconds, 5, 3600),
        ):
            if not minimum <= int(value) <= maximum:
                raise ValueError(f"{name} must be between {minimum} and {maximum}")

    def evidence(self) -> dict[str, int]:
        return {
            "requests_per_minute": self.requests_per_minute,
            "concurrent_requests": self.concurrent_requests,
            "circuit_failure_threshold": self.circuit_failure_threshold,
            "circuit_failure_window_seconds": self.circuit_failure_window_seconds,
            "circuit_open_seconds": self.circuit_open_seconds,
            "lease_seconds": self.lease_seconds,
        }


@dataclass(frozen=True, slots=True)
class ResolvedProviderModel:
    provider_id: str
    provider_type: str
    route_model: ValidatedProviderModel
    validated_at: datetime
    expires_at: datetime
    limits: ProjectAIProviderLimits

    @property
    def key(self) -> tuple[str, str]:
        return (self.provider_type, self.route_model.model)

    def evidence(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "provider": self.provider_type,
            "model": self.route_model.model,
            "evidence_ref": self.route_model.evidence_ref,
            "validated_at": self.validated_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "local": self.route_model.local,
            "coordination": self.limits.evidence(),
        }


class DurableProjectAIResolver:
    """Resolve one tenant's connected providers into explicit validated models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def resolve(
        self,
        scope: ProjectAIScope,
        provider_policy: ProjectAIProviderPolicy,
        *,
        now: datetime | None = None,
    ) -> tuple[ResolvedProviderModel, ...]:
        current = (now or datetime.now(UTC)).astimezone(UTC)
        execution = await self.session.get(ProjectExecution, scope.execution_id)
        if execution is None:
            raise ProjectAIDurableRoutingError("ProjectExecution was not found")
        expected = (
            execution.organization_id,
            execution.workspace_id,
            execution.project_id,
            execution.id,
        )
        actual = (
            scope.organization_id,
            scope.workspace_id,
            scope.project_id,
            scope.execution_id,
        )
        if expected != actual:
            raise ProjectAIDurableRoutingError("Project AI scope does not match ProjectExecution")

        rows = list(
            (
                await self.session.scalars(
                    select(AIProvider)
                    .where(
                        AIProvider.organization_id
                        == (
                            provider_policy.provider_scope_organization_id
                            or scope.organization_id
                        ),
                        AIProvider.status == "connected",
                    )
                    .order_by(AIProvider.type.asc(), AIProvider.id.asc())
                )
            ).all()
        )
        allowed = set(provider_policy.allowed_providers) - set(
            provider_policy.blocked_providers
        )
        resolved: list[ResolvedProviderModel] = []
        seen: set[tuple[str, str]] = set()
        for provider in rows:
            provider_type = provider.type.strip().lower()
            if provider_type not in allowed:
                continue
            config = dict(provider.config or {})
            if not bool(config.get("enabled", True)):
                continue
            raw_models = config.get("validated_models")
            if not isinstance(raw_models, list):
                continue
            for raw in raw_models:
                item = self._parse_model(provider, raw, current)
                if item is None:
                    continue
                if provider_policy.allowed_provider_models:
                    route_key = f"{item.provider_type}:{item.route_model.model}".lower()
                    if route_key not in provider_policy.allowed_provider_models:
                        continue
                if item.key in seen:
                    raise ProjectAIDurableRoutingError(
                        "multiple connected provider records claim the same validated model"
                    )
                seen.add(item.key)
                resolved.append(item)
        if not resolved:
            raise ProjectAIDurableRoutingError(
                "no connected tenant provider has current validated model evidence"
            )
        return tuple(sorted(resolved, key=lambda item: item.key))

    @staticmethod
    def _parse_model(
        provider: AIProvider,
        raw: Any,
        now: datetime,
    ) -> ResolvedProviderModel | None:
        if not isinstance(raw, dict):
            raise ProjectAIDurableRoutingError("validated_models entries must be objects")
        provider_type = provider.type.strip().lower()
        model = _required(raw.get("model"), "validated model")
        if model.lower() == "default":
            raise ProjectAIDurableRoutingError(
                "default model aliases cannot be live routing evidence"
            )
        validated_at = _utc(raw.get("validated_at"), "validated_at")
        expires_at = _utc(raw.get("expires_at"), "expires_at")
        if validated_at > now:
            raise ProjectAIDurableRoutingError("validated model evidence is future-dated")
        if expires_at <= now:
            return None
        tasks_raw = raw.get("tasks")
        if not isinstance(tasks_raw, list) or not tasks_raw:
            raise ProjectAIDurableRoutingError("validated model tasks must be non-empty")
        tasks = frozenset(_required(item, "validated model task") for item in tasks_raw)
        route_model = ValidatedProviderModel(
            provider=provider_type,
            model=model,
            tasks=tasks,
            evidence_ref=_required(raw.get("evidence_ref"), "evidence_ref"),
            languages=frozenset(str(item) for item in raw.get("languages", ["multilingual"])),
            supports_tools=bool(raw.get("supports_tools", False)),
            supports_vision=bool(raw.get("supports_vision", False)),
            supports_audio=bool(raw.get("supports_audio", False)),
            local=bool(raw.get("local", False)),
            max_context_tokens=int(raw.get("max_context_tokens", 0)),
            quality_score=float(raw.get("quality_score", -1)),
            latency_score=float(raw.get("latency_score", -1)),
            privacy_score=float(raw.get("privacy_score", -1)),
            input_cost_per_million=float(raw.get("input_cost_per_million", -1)),
            output_cost_per_million=float(raw.get("output_cost_per_million", -1)),
        )
        limits = ProjectAIProviderLimits(
            requests_per_minute=int(raw.get("requests_per_minute", 0)),
            concurrent_requests=int(raw.get("concurrent_requests", 0)),
            circuit_failure_threshold=int(raw.get("circuit_failure_threshold", 0)),
            circuit_failure_window_seconds=int(
                raw.get("circuit_failure_window_seconds", 0)
            ),
            circuit_open_seconds=int(raw.get("circuit_open_seconds", 0)),
            lease_seconds=int(raw.get("lease_seconds", 120)),
        )
        return ResolvedProviderModel(
            provider_id=provider.id,
            provider_type=provider_type,
            route_model=route_model,
            validated_at=validated_at,
            expires_at=expires_at,
            limits=limits,
        )


class DurableProjectAIRouteStore:
    """Persist prompt-free route plans, tasks, budget and audit evidence."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_plan(
        self,
        scope: ProjectAIScope,
        tasks: tuple[ProjectAITaskSpec, ...],
        provider_policy: ProjectAIProviderPolicy,
        *,
        now: datetime | None = None,
    ) -> ProjectAIRoutePlanRecord:
        current = now or datetime.now(UTC)
        resolver = DurableProjectAIResolver(self.session)
        models = await resolver.resolve(scope, provider_policy, now=current)
        planner = ProjectAIRoutePlanner(tuple(item.route_model for item in models))
        plan = planner.plan(scope, tasks, provider_policy)
        by_key = {item.key: item for item in models}
        fingerprint = self._fingerprint(plan, provider_policy, by_key)

        latest = await self.session.scalar(
            select(ProjectAIRoutePlanRecord)
            .where(ProjectAIRoutePlanRecord.execution_id == scope.execution_id)
            .order_by(ProjectAIRoutePlanRecord.plan_version.desc())
            .limit(1)
            .with_for_update()
        )
        if latest is not None:
            if (latest.evidence or {}).get("plan_fingerprint") == fingerprint:
                return latest
            if latest.status in {"planned", "active"}:
                raise ProjectAIDurableRoutingError(
                    "an active durable Project AI route plan already exists"
                )
            version = latest.plan_version + 1
        else:
            version = 1

        execution = await self.session.get(ProjectExecution, scope.execution_id)
        if execution is None:  # pragma: no cover - resolver already proves this
            raise ProjectAIDurableRoutingError("ProjectExecution disappeared")
        budget_limit = float(execution.budget_cap_usd)
        if provider_policy.max_total_estimated_cost_usd is not None:
            budget_limit = min(
                budget_limit,
                float(provider_policy.max_total_estimated_cost_usd),
            )
        limit_microusd = usd_to_microusd(budget_limit)
        total_estimated = usd_to_microusd(
            plan.total_primary_estimated_cost_usd, reserve=True
        )
        if total_estimated > limit_microusd:
            raise ProjectAIBudgetExceeded("route plan exceeds durable execution budget")

        record = ProjectAIRoutePlanRecord(
            id=str(uuid4()),
            organization_id=scope.organization_id,
            workspace_id=scope.workspace_id,
            project_id=scope.project_id,
            execution_id=scope.execution_id,
            plan_version=version,
            status="planned",
            policy=self._policy_evidence(provider_policy),
            evidence={**plan.evidence(), "plan_fingerprint": fingerprint},
            total_primary_estimated_microusd=total_estimated,
        )
        self.session.add(record)
        await self.session.flush()

        for task_plan in plan.tasks:
            candidates = []
            for candidate in task_plan.candidates:
                resolved = by_key[(candidate.provider, candidate.model)]
                candidates.append(
                    {
                        **candidate.evidence(),
                        "provider_id": resolved.provider_id,
                        "validated_at": resolved.validated_at.isoformat(),
                        "expires_at": resolved.expires_at.isoformat(),
                        "coordination": resolved.limits.evidence(),
                    }
                )
            primary = candidates[0]
            self.session.add(
                ProjectAIRouteTaskRecord(
                    id=str(uuid4()),
                    plan_id=record.id,
                    organization_id=scope.organization_id,
                    task_id=task_plan.task_id,
                    role=task_plan.role,
                    task=task_plan.task,
                    primary_provider_id=str(primary["provider_id"]),
                    primary_provider_type=str(primary["provider"]),
                    primary_model=str(primary["model"]),
                    candidates=candidates,
                    estimated_microusd=usd_to_microusd(
                        float(primary["estimated_cost_usd"]), reserve=True
                    ),
                    status="planned",
                    evidence_ref=str(primary["evidence_ref"]),
                )
            )

        budget = await self.session.get(ProjectAIExecutionBudget, scope.execution_id)
        if budget is None:
            self.session.add(
                ProjectAIExecutionBudget(
                    execution_id=scope.execution_id,
                    organization_id=scope.organization_id,
                    limit_microusd=limit_microusd,
                    reserved_microusd=0,
                    spent_microusd=0,
                )
            )
        elif budget.organization_id != scope.organization_id:
            raise ProjectAIDurableRoutingError("execution budget tenant scope mismatch")

        self.session.add(
            AuditEvent(
                organization_id=scope.organization_id,
                user_id=None,
                action="project.ai.route_plan.created",
                resource_type="project_ai_route_plan",
                resource_id=record.id,
                details={
                    "execution_id": scope.execution_id,
                    "project_id": scope.project_id,
                    "plan_version": version,
                    "task_count": len(plan.tasks),
                    "providers": record.evidence.get("providers", []),
                    "total_primary_estimated_microusd": total_estimated,
                    "plan_fingerprint": fingerprint,
                },
            )
        )
        await self.session.flush()
        return record

    @staticmethod
    def _policy_evidence(policy: ProjectAIProviderPolicy) -> dict[str, Any]:
        return {
            "allowed_providers": sorted(policy.allowed_providers),
            "blocked_providers": sorted(policy.blocked_providers),
            "allowed_provider_models": sorted(policy.allowed_provider_models),
            "provider_scope_organization_id": policy.provider_scope_organization_id,
            "offline_only": policy.offline_only,
            "privacy_mode": policy.privacy_mode,
            "max_total_estimated_cost_usd": policy.max_total_estimated_cost_usd,
        }

    @staticmethod
    def _fingerprint(
        plan: ProjectAIRoutePlan,
        policy: ProjectAIProviderPolicy,
        models: dict[tuple[str, str], ResolvedProviderModel],
    ) -> str:
        model_evidence = [models[key].evidence() for key in sorted(models)]
        payload = {
            "plan": plan.evidence(),
            "policy": DurableProjectAIRouteStore._policy_evidence(policy),
            "models": model_evidence,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


_ACQUIRE_SCRIPT = """
if redis.call('EXISTS', KEYS[3]) == 1 then
  return -3
end
local now = redis.call('TIME')
local now_ms = (tonumber(now[1]) * 1000) + math.floor(tonumber(now[2]) / 1000)
redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', now_ms)
if redis.call('ZCARD', KEYS[2]) >= tonumber(ARGV[3]) then
  return -2
end
local rate = redis.call('INCR', KEYS[1])
if rate == 1 then
  redis.call('PEXPIRE', KEYS[1], tonumber(ARGV[5]))
end
if rate > tonumber(ARGV[2]) then
  return -1
end
local expires_ms = now_ms + tonumber(ARGV[4])
redis.call('ZADD', KEYS[2], expires_ms, ARGV[1])
redis.call('PEXPIRE', KEYS[2], tonumber(ARGV[4]) + 5000)
return 1
"""

_RELEASE_SCRIPT = "return redis.call('ZREM', KEYS[1], ARGV[1])"

_FAILURE_SCRIPT = """
if redis.call('SETNX', KEYS[3], '1') == 0 then
  return tonumber(redis.call('GET', KEYS[1]) or '0')
end
redis.call('PEXPIRE', KEYS[3], tonumber(ARGV[4]))
local failures = redis.call('INCR', KEYS[1])
if failures == 1 then
  redis.call('PEXPIRE', KEYS[1], tonumber(ARGV[2]))
end
if failures >= tonumber(ARGV[1]) then
  redis.call('SET', KEYS[2], '1', 'PX', tonumber(ARGV[3]))
end
return failures
"""

_SUCCESS_SCRIPT = """
if redis.call('SETNX', KEYS[2], '1') == 0 then
  return 0
end
redis.call('PEXPIRE', KEYS[2], tonumber(ARGV[1]))
redis.call('DEL', KEYS[1])
return 1
"""


@dataclass(frozen=True, slots=True)
class ProjectAICoordinationLease:
    token: str
    digest: str
    provider_id: str
    model: str
    limits: ProjectAIProviderLimits


class ProjectAISharedCoordinator:
    """Redis authority shared by all distributed Project Workers."""

    def __init__(self, redis_client: Any, *, key_prefix: str = "aionex:project-ai:coord:v1") -> None:
        self.redis = redis_client
        self.key_prefix = key_prefix.strip()
        if not self.key_prefix:
            raise ValueError("Project AI coordination key prefix is required")

    @staticmethod
    def _digest(organization_id: str, provider_id: str, model: str) -> str:
        material = f"{organization_id}\0{provider_id}\0{model}".encode("utf-8")
        return hashlib.sha256(material).hexdigest()

    def _keys(self, digest: str) -> tuple[str, str, str, str]:
        base = f"{self.key_prefix}:{digest}"
        return (
            f"{base}:rate",
            f"{base}:concurrency",
            f"{base}:circuit",
            f"{base}:failures",
        )

    async def acquire(
        self,
        *,
        organization_id: str,
        provider_id: str,
        model: str,
        limits: ProjectAIProviderLimits,
    ) -> ProjectAICoordinationLease:
        digest = self._digest(organization_id, provider_id, model)
        rate_key, concurrency_key, circuit_key, _ = self._keys(digest)
        token = str(uuid4())
        try:
            result = int(
                await self.redis.eval(
                    _ACQUIRE_SCRIPT,
                    3,
                    rate_key,
                    concurrency_key,
                    circuit_key,
                    token,
                    limits.requests_per_minute,
                    limits.concurrent_requests,
                    limits.lease_seconds * 1000,
                    60_000,
                )
            )
        except (RedisError, TypeError, ValueError) as exc:
            raise ProjectAISharedCoordinationError(
                "shared Project AI provider coordination is unavailable"
            ) from exc
        if result == -1:
            raise ProjectAIProviderRateLimited("provider request rate limit reached")
        if result == -2:
            raise ProjectAIProviderConcurrencyLimited(
                "provider concurrent request limit reached"
            )
        if result == -3:
            raise ProjectAIProviderCircuitOpen("provider/model circuit is open")
        if result != 1:
            raise ProjectAISharedCoordinationError(
                "shared provider coordinator returned an invalid state"
            )
        return ProjectAICoordinationLease(
            token=token,
            digest=digest,
            provider_id=provider_id,
            model=model,
            limits=limits,
        )

    async def release(self, lease: ProjectAICoordinationLease) -> bool:
        _, concurrency_key, _, _ = self._keys(lease.digest)
        try:
            await self.redis.eval(_RELEASE_SCRIPT, 1, concurrency_key, lease.token)
        except RedisError:
            # Concurrency leases are server-time bounded and self-clean.  An already
            # persisted result must not become a false failure solely because Redis
            # disappeared during best-effort release.
            return False
        return True

    def _finalization_key(self, digest: str, event_id: str) -> str:
        event_digest = hashlib.sha256(event_id.encode("utf-8")).hexdigest()
        return f"{self.key_prefix}:{digest}:finalized:{event_digest}"

    async def record_failure(
        self, lease: ProjectAICoordinationLease, *, event_id: str
    ) -> int:
        _, _, circuit_key, failures_key = self._keys(lease.digest)
        finalization_key = self._finalization_key(lease.digest, event_id)
        try:
            return int(
                await self.redis.eval(
                    _FAILURE_SCRIPT,
                    3,
                    failures_key,
                    circuit_key,
                    finalization_key,
                    lease.limits.circuit_failure_threshold,
                    lease.limits.circuit_failure_window_seconds * 1000,
                    lease.limits.circuit_open_seconds * 1000,
                    86_400_000,
                )
            )
        except (RedisError, TypeError, ValueError) as exc:
            raise ProjectAISharedCoordinationError(
                "shared provider failure state could not be recorded"
            ) from exc

    async def record_success(
        self, lease: ProjectAICoordinationLease, *, event_id: str
    ) -> None:
        _, _, _, failures_key = self._keys(lease.digest)
        finalization_key = self._finalization_key(lease.digest, event_id)
        try:
            await self.redis.eval(
                _SUCCESS_SCRIPT,
                2,
                failures_key,
                finalization_key,
                86_400_000,
            )
        except RedisError as exc:
            raise ProjectAISharedCoordinationError(
                "shared provider success state could not be recorded"
            ) from exc


@dataclass(frozen=True, slots=True)
class ProjectAIAttemptPermit:
    attempt_id: str
    task_route_id: str
    execution_id: str
    organization_id: str
    provider_id: str
    provider_type: str
    model: str
    candidate_index: int
    reserved_microusd: int
    coordination: ProjectAICoordinationLease


class DurableProjectAIAuthority:
    """Coordinate one provider attempt across Redis and PostgreSQL authorities."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        coordinator: ProjectAISharedCoordinator,
    ) -> None:
        self.session_factory = session_factory
        self.coordinator = coordinator

    async def begin_attempt(
        self,
        scope: ProjectAIScope,
        *,
        task_id: str,
        candidate_index: int,
    ) -> ProjectAIAttemptPermit:
        if candidate_index < 0:
            raise ValueError("candidate_index must be non-negative")
        async with self.session_factory() as session:
            route = await self._load_task(session, scope, task_id)
            if route.status == "completed":
                raise ProjectAIDurableRoutingError("Project AI task route is already completed")
            if route.status == "running":
                raise ProjectAIDurableRoutingError("Project AI task route already has an active attempt")
            try:
                candidate = dict(route.candidates[candidate_index])
            except IndexError as exc:
                raise ProjectAIDurableRoutingError("route candidate index is out of range") from exc
            limits = ProjectAIProviderLimits(**dict(candidate["coordination"]))
            provider_id = _required(candidate.get("provider_id"), "provider_id")
            provider_type = _required(candidate.get("provider"), "provider")
            model = _required(candidate.get("model"), "model")
            evidence_ref = _required(candidate.get("evidence_ref"), "evidence_ref")
            estimated = usd_to_microusd(
                float(candidate.get("estimated_cost_usd", 0.0)), reserve=True
            )

        lease = await self.coordinator.acquire(
            organization_id=scope.organization_id,
            provider_id=provider_id,
            model=model,
            limits=limits,
        )
        try:
            async with self.session_factory() as session:
                async with session.begin():
                    route = await self._load_task(
                        session, scope, task_id, for_update=True
                    )
                    if route.status == "completed":
                        raise ProjectAIDurableRoutingError(
                            "Project AI task route is already completed"
                        )
                    if route.status == "running":
                        raise ProjectAIDurableRoutingError(
                            "Project AI task route already has an active attempt"
                        )
                    budget = await session.scalar(
                        select(ProjectAIExecutionBudget)
                        .where(
                            ProjectAIExecutionBudget.execution_id == scope.execution_id
                        )
                        .with_for_update()
                    )
                    if budget is None or budget.organization_id != scope.organization_id:
                        raise ProjectAIDurableRoutingError(
                            "durable Project AI execution budget is missing or out of scope"
                        )
                    if budget.spent_microusd + budget.reserved_microusd + estimated > budget.limit_microusd:
                        raise ProjectAIBudgetExceeded(
                            "durable Project AI execution budget is exhausted"
                        )
                    attempt_index = int(
                        await session.scalar(
                            select(func.coalesce(func.max(ProjectAIRouteAttemptRecord.attempt_index), 0)).where(
                                ProjectAIRouteAttemptRecord.task_route_id == route.id
                            )
                        )
                        or 0
                    ) + 1
                    attempt = ProjectAIRouteAttemptRecord(
                        id=str(uuid4()),
                        task_route_id=route.id,
                        organization_id=scope.organization_id,
                        execution_id=scope.execution_id,
                        provider_id=provider_id,
                        provider_type=provider_type,
                        model=model,
                        attempt_index=attempt_index,
                        status="reserved",
                        fallback_used=candidate_index > 0,
                        estimated_microusd=estimated,
                        reserved_microusd=estimated,
                        actual_microusd=0,
                        latency_ms=0.0,
                        evidence_ref=evidence_ref,
                        started_at=datetime.now(UTC),
                    )
                    session.add(attempt)
                    budget.reserved_microusd += estimated
                    route.status = "running"
                    plan = await session.get(ProjectAIRoutePlanRecord, route.plan_id)
                    if plan is not None:
                        plan.status = "active"
                    session.add(
                        AuditEvent(
                            organization_id=scope.organization_id,
                            user_id=None,
                            action="project.ai.route_attempt.reserved",
                            resource_type="project_ai_route_attempt",
                            resource_id=attempt.id,
                            details={
                                "execution_id": scope.execution_id,
                                "task_id": task_id,
                                "provider_id": provider_id,
                                "provider": provider_type,
                                "model": model,
                                "candidate_index": candidate_index,
                                "reserved_microusd": estimated,
                                "evidence_ref": evidence_ref,
                            },
                        )
                    )
                return ProjectAIAttemptPermit(
                    attempt_id=attempt.id,
                    task_route_id=route.id,
                    execution_id=scope.execution_id,
                    organization_id=scope.organization_id,
                    provider_id=provider_id,
                    provider_type=provider_type,
                    model=model,
                    candidate_index=candidate_index,
                    reserved_microusd=estimated,
                    coordination=lease,
                )
        except BaseException:
            await self.coordinator.release(lease)
            raise

    async def finish_attempt(
        self,
        permit: ProjectAIAttemptPermit,
        *,
        success: bool,
        actual_cost_usd: float,
        latency_ms: float,
        error_code: str | None = None,
    ) -> None:
        actual = usd_to_microusd(actual_cost_usd)
        if latency_ms < 0:
            raise ValueError("latency_ms must be non-negative")
        try:
            async with self.session_factory() as session:
                async with session.begin():
                    attempt = await session.scalar(
                        select(ProjectAIRouteAttemptRecord)
                        .where(ProjectAIRouteAttemptRecord.id == permit.attempt_id)
                        .with_for_update()
                    )
                    if attempt is None:
                        raise ProjectAIDurableRoutingError("Project AI attempt was not found")
                    if (
                        attempt.organization_id != permit.organization_id
                        or attempt.execution_id != permit.execution_id
                        or attempt.provider_id != permit.provider_id
                        or attempt.model != permit.model
                    ):
                        raise ProjectAIDurableRoutingError("Project AI attempt permit mismatch")
                    terminal_status = "succeeded" if success else "failed"
                    already_terminal = attempt.status in {"succeeded", "failed"}
                    if already_terminal and attempt.status != terminal_status:
                        raise ProjectAIDurableRoutingError(
                            "Project AI attempt terminal outcome does not match retry"
                        )
                    if not already_terminal and attempt.status != "reserved":
                        raise ProjectAIDurableRoutingError(
                            "Project AI attempt is no longer reservable"
                        )
                    budget = await session.scalar(
                        select(ProjectAIExecutionBudget)
                        .where(
                            ProjectAIExecutionBudget.execution_id == permit.execution_id
                        )
                        .with_for_update()
                    )
                    if budget is None or budget.organization_id != permit.organization_id:
                        raise ProjectAIDurableRoutingError(
                            "durable Project AI execution budget is missing or out of scope"
                        )
                    if not already_terminal:
                        budget.reserved_microusd = max(
                            0, budget.reserved_microusd - attempt.reserved_microusd
                        )
                        budget.spent_microusd += actual
                        attempt.actual_microusd = actual
                        attempt.latency_ms = float(latency_ms)
                        attempt.error_code = None if success else _required(error_code, "error_code")
                        attempt.status = terminal_status
                        attempt.completed_at = datetime.now(UTC)
                    route = await session.scalar(
                        select(ProjectAIRouteTaskRecord)
                        .where(ProjectAIRouteTaskRecord.id == attempt.task_route_id)
                        .with_for_update()
                    )
                    if route is None:
                        raise ProjectAIDurableRoutingError("Project AI task route was not found")
                    if not already_terminal:
                        if success:
                            route.status = "completed"
                            route.selected_provider_id = attempt.provider_id
                            route.selected_provider_type = attempt.provider_type
                            route.selected_model = attempt.model
                            route.evidence_ref = attempt.evidence_ref
                        else:
                            route.status = "planned"
                    over_budget = budget.spent_microusd + budget.reserved_microusd > budget.limit_microusd
                    if not already_terminal:
                        session.add(
                            AuditEvent(
                            organization_id=permit.organization_id,
                            user_id=None,
                            action=(
                                "project.ai.route_attempt.succeeded"
                                if success
                                else "project.ai.route_attempt.failed"
                            ),
                            resource_type="project_ai_route_attempt",
                            resource_id=attempt.id,
                            details={
                                "execution_id": permit.execution_id,
                                "provider_id": permit.provider_id,
                                "provider": permit.provider_type,
                                "model": permit.model,
                                "actual_microusd": actual,
                                "latency_ms": float(latency_ms),
                                "error_code": attempt.error_code,
                                "over_budget": over_budget,
                            },
                            )
                        )
                    if success and not already_terminal:
                        remaining = int(
                            await session.scalar(
                                select(func.count(ProjectAIRouteTaskRecord.id)).where(
                                    ProjectAIRouteTaskRecord.plan_id == route.plan_id,
                                    ProjectAIRouteTaskRecord.status != "completed",
                                )
                            )
                            or 0
                        )
                        if remaining == 0:
                            plan = await session.get(ProjectAIRoutePlanRecord, route.plan_id)
                            if plan is not None:
                                plan.status = "completed"
            if success:
                await self.coordinator.record_success(
                    permit.coordination, event_id=permit.attempt_id
                )
            else:
                await self.coordinator.record_failure(
                    permit.coordination, event_id=permit.attempt_id
                )
        finally:
            await self.coordinator.release(permit.coordination)

    @staticmethod
    async def _load_task(
        session: AsyncSession,
        scope: ProjectAIScope,
        task_id: str,
        *,
        for_update: bool = False,
    ) -> ProjectAIRouteTaskRecord:
        statement = (
            select(ProjectAIRouteTaskRecord)
            .join(
                ProjectAIRoutePlanRecord,
                ProjectAIRoutePlanRecord.id == ProjectAIRouteTaskRecord.plan_id,
            )
            .where(
                ProjectAIRouteTaskRecord.task_id == task_id,
                ProjectAIRouteTaskRecord.organization_id == scope.organization_id,
                ProjectAIRoutePlanRecord.organization_id == scope.organization_id,
                ProjectAIRoutePlanRecord.workspace_id == scope.workspace_id,
                ProjectAIRoutePlanRecord.project_id == scope.project_id,
                ProjectAIRoutePlanRecord.execution_id == scope.execution_id,
            )
        )
        if for_update:
            statement = statement.with_for_update()
        route = await session.scalar(statement)
        if route is None:
            raise ProjectAIDurableRoutingError("Project AI task route was not found in scope")
        return route
