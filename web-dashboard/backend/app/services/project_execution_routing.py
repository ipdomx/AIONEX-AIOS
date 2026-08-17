"""Phase 36C tenant-safe ProjectExecution AI route-plan foundation.

This module is intentionally isolated from live provider credentials and production
mutation.  It converts validated runtime model capabilities into the existing AIOS
routing layer, emits prompt-free audit evidence, and provides an injected-transport
adapter for deterministic acceptance tests.  Durable provider resolution, shared
quota/circuit state, and live ProjectExecution wiring are later 36C gates.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Mapping

from aios.providers import (
    AIRoutingLayer,
    DataSensitivity,
    ExecutionMode,
    ModelCapability,
    ModelRequest,
    MultiModelPlatform,
    OptimizationMode,
    RoutingPolicy,
    Transport,
)
from aios.providers.adapters.generic import GenericProvider


class ProjectAIRoutingError(RuntimeError):
    """Raised when a tenant-safe Project AI route cannot be proven."""


def _required(value: str, label: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{label} is required")
    return normalized


@dataclass(frozen=True, slots=True)
class ProjectAIScope:
    organization_id: str
    workspace_id: str
    project_id: str
    execution_id: str

    def __post_init__(self) -> None:
        for field_name in (
            "organization_id",
            "workspace_id",
            "project_id",
            "execution_id",
        ):
            object.__setattr__(
                self,
                field_name,
                _required(getattr(self, field_name), field_name),
            )

    @property
    def policy_scope(self) -> str:
        return f"org:{self.organization_id}:project:{self.project_id}"

    @property
    def budget_scope(self) -> str:
        return (
            f"org:{self.organization_id}:project:{self.project_id}:"
            f"execution:{self.execution_id}"
        )

    def evidence(self) -> dict[str, str]:
        return {
            "organization_id": self.organization_id,
            "workspace_id": self.workspace_id,
            "project_id": self.project_id,
            "execution_id": self.execution_id,
            "policy_scope": self.policy_scope,
            "budget_scope": self.budget_scope,
        }


@dataclass(frozen=True, slots=True)
class ValidatedProviderModel:
    provider: str
    model: str
    tasks: frozenset[str]
    evidence_ref: str
    languages: frozenset[str] = frozenset({"multilingual"})
    supports_tools: bool = False
    supports_vision: bool = False
    supports_audio: bool = False
    local: bool = False
    max_context_tokens: int = 8192
    quality_score: float = 0.5
    latency_score: float = 0.5
    privacy_score: float = 0.5
    input_cost_per_million: float = 0.0
    output_cost_per_million: float = 0.0

    def __post_init__(self) -> None:
        provider = _required(self.provider, "provider").lower()
        model = _required(self.model, "model")
        evidence_ref = _required(self.evidence_ref, "evidence_ref")
        tasks = frozenset(_required(item, "task") for item in self.tasks)
        if model.lower() == "default":
            raise ValueError("default model aliases are not valid runtime evidence")
        if not tasks:
            raise ValueError("validated provider model must declare at least one task")
        if self.max_context_tokens <= 0:
            raise ValueError("max_context_tokens must be positive")
        for label, value in (
            ("quality_score", self.quality_score),
            ("latency_score", self.latency_score),
            ("privacy_score", self.privacy_score),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{label} must be between 0 and 1")
        if self.input_cost_per_million < 0 or self.output_cost_per_million < 0:
            raise ValueError("model pricing must be non-negative")
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "model", model)
        object.__setattr__(self, "evidence_ref", evidence_ref)
        object.__setattr__(self, "tasks", tasks)
        object.__setattr__(
            self,
            "languages",
            frozenset(str(item).strip() for item in self.languages if str(item).strip()),
        )

    def capability(self) -> ModelCapability:
        return ModelCapability(
            provider=self.provider,
            model=self.model,
            tasks=self.tasks,
            languages=self.languages,
            supports_tools=self.supports_tools,
            supports_vision=self.supports_vision,
            supports_audio=self.supports_audio,
            local=self.local,
            max_context_tokens=self.max_context_tokens,
            quality_score=self.quality_score,
            latency_score=self.latency_score,
            privacy_score=self.privacy_score,
            input_cost_per_million=self.input_cost_per_million,
            output_cost_per_million=self.output_cost_per_million,
        )


@dataclass(frozen=True, slots=True)
class ProjectAIProviderPolicy:
    allowed_providers: frozenset[str]
    blocked_providers: frozenset[str] = frozenset()
    allowed_provider_models: frozenset[str] = frozenset()
    provider_scope_organization_id: str | None = None
    max_fallbacks: int = 1
    offline_only: bool = False
    privacy_mode: bool = False
    max_total_estimated_cost_usd: float | None = None

    def __post_init__(self) -> None:
        allowed = frozenset(
            _required(item, "allowed provider").lower() for item in self.allowed_providers
        )
        blocked = frozenset(
            _required(item, "blocked provider").lower() for item in self.blocked_providers
        )
        if not allowed:
            raise ValueError("allowed_providers must be explicit and non-empty")
        if allowed & blocked:
            raise ValueError("a provider cannot be both allowed and blocked")
        allowed_models = frozenset(
            _required(item, "allowed provider model").lower()
            for item in self.allowed_provider_models
        )
        for item in allowed_models:
            if ":" not in item or item.startswith(":") or item.endswith(":"):
                raise ValueError("allowed_provider_models entries must be provider:model")
            provider_name, _model = item.split(":", 1)
            if provider_name not in allowed:
                raise ValueError("allowed provider model references a provider outside allowed_providers")
        provider_scope = (self.provider_scope_organization_id or "").strip() or None
        if not 0 <= int(self.max_fallbacks) <= 4:
            raise ValueError("max_fallbacks must be between 0 and 4")
        if (
            self.max_total_estimated_cost_usd is not None
            and self.max_total_estimated_cost_usd < 0
        ):
            raise ValueError("max_total_estimated_cost_usd must be non-negative")
        object.__setattr__(self, "allowed_providers", allowed)
        object.__setattr__(self, "blocked_providers", blocked)
        object.__setattr__(self, "allowed_provider_models", allowed_models)
        object.__setattr__(self, "provider_scope_organization_id", provider_scope)


PROJECT_AI_ROLES = frozenset({"planner", "researcher", "coder", "reviewer", "media"})


@dataclass(frozen=True, slots=True)
class ProjectAITaskSpec:
    task_id: str
    role: str
    task: str
    prompt: str = field(repr=False)
    system_prompt: str = field(default="", repr=False)
    sensitivity: DataSensitivity = DataSensitivity.INTERNAL
    max_cost_usd: float | None = None
    max_tokens: int = 1024
    require_local: bool = False
    require_tools: bool = False
    require_vision: bool = False
    require_audio: bool = False
    optimization: OptimizationMode = OptimizationMode.BALANCED
    allow_failover: bool = True
    provider_priority: tuple[str, ...] = ()
    excluded_providers: frozenset[str] = frozenset()
    max_fallbacks: int = 1

    def __post_init__(self) -> None:
        task_id = _required(self.task_id, "task_id")
        role = _required(self.role, "role").lower()
        task = _required(self.task, "task").lower()
        prompt = _required(self.prompt, "prompt")
        if role not in PROJECT_AI_ROLES:
            raise ValueError(f"unsupported Project AI role: {role}")
        if self.max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        if self.max_cost_usd is not None and self.max_cost_usd < 0:
            raise ValueError("max_cost_usd must be non-negative")
        if self.max_fallbacks < 0:
            raise ValueError("max_fallbacks must be non-negative")
        object.__setattr__(self, "task_id", task_id)
        object.__setattr__(self, "role", role)
        object.__setattr__(self, "task", task)
        object.__setattr__(self, "prompt", prompt)
        object.__setattr__(
            self,
            "provider_priority",
            tuple(_required(item, "provider priority").lower() for item in self.provider_priority),
        )
        object.__setattr__(
            self,
            "excluded_providers",
            frozenset(
                _required(item, "excluded provider").lower()
                for item in self.excluded_providers
            ),
        )

    def model_request(self) -> ModelRequest:
        return ModelRequest(
            task=self.task,
            prompt=self.prompt,
            system_prompt=self.system_prompt,
            sensitivity=self.sensitivity,
            max_cost=self.max_cost_usd,
            max_tokens=self.max_tokens,
            require_local=self.require_local,
            require_tools=self.require_tools,
            require_vision=self.require_vision,
            require_audio=self.require_audio,
            metadata={"role": self.role, "task_id": self.task_id},
        )


@dataclass(frozen=True, slots=True)
class ProjectAIRouteCandidate:
    provider: str
    model: str
    score: float
    estimated_cost_usd: float
    reasons: tuple[str, ...]
    evidence_ref: str
    local: bool

    def evidence(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "score": self.score,
            "estimated_cost_usd": self.estimated_cost_usd,
            "reasons": list(self.reasons),
            "evidence_ref": self.evidence_ref,
            "local": self.local,
        }


@dataclass(frozen=True, slots=True)
class ProjectAITaskPlan:
    task_id: str
    role: str
    task: str
    primary: ProjectAIRouteCandidate
    fallbacks: tuple[ProjectAIRouteCandidate, ...] = ()

    @property
    def candidates(self) -> tuple[ProjectAIRouteCandidate, ...]:
        return (self.primary, *self.fallbacks)

    def evidence(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "role": self.role,
            "task": self.task,
            "primary": self.primary.evidence(),
            "fallbacks": [item.evidence() for item in self.fallbacks],
        }


@dataclass(frozen=True, slots=True)
class ProjectAIRoutePlan:
    scope: ProjectAIScope
    tasks: tuple[ProjectAITaskPlan, ...]
    total_primary_estimated_cost_usd: float

    def evidence(self) -> dict[str, Any]:
        return {
            "scope": self.scope.evidence(),
            "tasks": [item.evidence() for item in self.tasks],
            "total_primary_estimated_cost_usd": self.total_primary_estimated_cost_usd,
            "providers": sorted(
                {candidate.provider for task in self.tasks for candidate in task.candidates}
            ),
        }


@dataclass(frozen=True, slots=True)
class ProjectAITaskExecutionResult:
    task_id: str
    role: str
    provider: str
    model: str
    text: str = field(repr=False)
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    fallback_used: bool = False
    attempted_routes: tuple[str, ...] = ()
    evidence_ref: str = ""

    def evidence(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "role": self.role,
            "provider": self.provider,
            "model": self.model,
            "cost_usd": self.cost_usd,
            "latency_ms": self.latency_ms,
            "fallback_used": self.fallback_used,
            "attempted_routes": list(self.attempted_routes),
            "evidence_ref": self.evidence_ref,
        }


class ProjectAIRoutePlanner:
    """Build prompt-free per-task route plans from validated model evidence."""

    def __init__(self, models: tuple[ValidatedProviderModel, ...]) -> None:
        if not models:
            raise ValueError("at least one validated provider model is required")
        self.models = models
        self._model_by_key: dict[tuple[str, str], ValidatedProviderModel] = {}
        for item in models:
            key = (item.provider, item.model)
            if key in self._model_by_key:
                raise ValueError(f"duplicate validated provider model: {item.provider}/{item.model}")
            self._model_by_key[key] = item

    def _platform(
        self,
        transports: Mapping[str, Transport] | None = None,
        *,
        models: tuple[ValidatedProviderModel, ...] | None = None,
    ) -> MultiModelPlatform:
        selected = models or self.models
        platform = MultiModelPlatform()
        for provider in tuple(item.name for item in platform.registry.all()):
            platform.registry.unregister(provider)
        grouped: dict[str, list[ValidatedProviderModel]] = defaultdict(list)
        for item in selected:
            grouped[item.provider].append(item)
        for provider_name, provider_models in sorted(grouped.items()):
            transport = (transports or {}).get(provider_name)
            platform.registry.register(
                GenericProvider(
                    provider_name,
                    tuple(item.capability() for item in provider_models),
                    transport,
                )
            )
        return platform

    def plan(
        self,
        scope: ProjectAIScope,
        tasks: tuple[ProjectAITaskSpec, ...],
        provider_policy: ProjectAIProviderPolicy,
    ) -> ProjectAIRoutePlan:
        if not tasks:
            raise ProjectAIRoutingError("project AI route plan requires at least one task")
        task_ids = [item.task_id for item in tasks]
        if len(task_ids) != len(set(task_ids)):
            raise ProjectAIRoutingError("project AI task ids must be unique within an execution")

        platform = self._platform()
        available_provider_names = {item.name for item in platform.registry.all()}
        allowed = set(provider_policy.allowed_providers) - set(provider_policy.blocked_providers)
        allowed &= available_provider_names
        if not allowed:
            raise ProjectAIRoutingError("no validated provider is allowed by tenant policy")
        platform.policy.allowed_by_project[scope.policy_scope] = allowed
        layer = AIRoutingLayer(platform)

        planned: list[ProjectAITaskPlan] = []
        total_cost = 0.0
        for task in tasks:
            routing_policy = RoutingPolicy(
                optimization=task.optimization,
                execution=ExecutionMode.SINGLE,
                max_models=1,
                allow_failover=task.allow_failover,
                offline_only=provider_policy.offline_only,
                privacy_mode=provider_policy.privacy_mode,
                provider_priority=task.provider_priority,
                excluded_providers=frozenset(
                    set(provider_policy.blocked_providers)
                    | set(task.excluded_providers)
                ),
            )
            ranked = layer.rank(
                task.model_request(),
                routing_policy,
                project=scope.policy_scope,
                budget_scope=scope.budget_scope,
            )
            if not ranked:
                raise ProjectAIRoutingError(
                    f"no eligible validated provider route for task {task.task_id}"
                )
            affordable = ranked
            if provider_policy.max_total_estimated_cost_usd is not None:
                remaining_budget = max(
                    0.0,
                    float(provider_policy.max_total_estimated_cost_usd) - total_cost,
                )
                affordable = tuple(
                    item
                    for item in ranked
                    if float(item.estimated_cost) <= remaining_budget + 1e-12
                )
                if not affordable:
                    raise ProjectAIRoutingError(
                        "project AI route plan exceeds tenant budget ceiling"
                    )
            candidate_count = 1 + (task.max_fallbacks if task.allow_failover else 0)
            candidates = tuple(
                self._candidate(item.provider, item.model, item.score, item.estimated_cost, item.reasons)
                for item in affordable[:candidate_count]
            )
            primary = candidates[0]
            fallbacks = candidates[1:]
            total_cost += primary.estimated_cost_usd
            if (
                provider_policy.max_total_estimated_cost_usd is not None
                and total_cost > float(provider_policy.max_total_estimated_cost_usd) + 1e-12
            ):  # defensive: affordability filtering above should make this unreachable
                raise ProjectAIRoutingError("project AI route plan exceeds tenant budget ceiling")
            planned.append(
                ProjectAITaskPlan(
                    task_id=task.task_id,
                    role=task.role,
                    task=task.task,
                    primary=primary,
                    fallbacks=fallbacks,
                )
            )
        return ProjectAIRoutePlan(
            scope=scope,
            tasks=tuple(planned),
            total_primary_estimated_cost_usd=round(total_cost, 8),
        )

    def _candidate(
        self,
        provider: str,
        model: str,
        score: float,
        estimated_cost: float,
        reasons: tuple[str, ...],
    ) -> ProjectAIRouteCandidate:
        evidence = self._model_by_key[(provider, model)]
        return ProjectAIRouteCandidate(
            provider=provider,
            model=model,
            score=score,
            estimated_cost_usd=estimated_cost,
            reasons=reasons,
            evidence_ref=evidence.evidence_ref,
            local=evidence.local,
        )

    async def execute_deterministic(
        self,
        scope: ProjectAIScope,
        plan: ProjectAIRoutePlan,
        tasks: tuple[ProjectAITaskSpec, ...],
        transports: Mapping[str, Transport],
    ) -> tuple[ProjectAITaskExecutionResult, ...]:
        """Execute an isolated plan using only explicitly injected transports.

        This is an acceptance adapter, not the production durable provider resolver.
        It performs no network operation unless a caller deliberately injects a
        transport that does so.
        """

        if scope != plan.scope:
            raise ProjectAIRoutingError("execution scope does not match route plan scope")
        specs = {item.task_id: item for item in tasks}
        if set(specs) != {item.task_id for item in plan.tasks}:
            raise ProjectAIRoutingError("execution task set does not match route plan")

        results: list[ProjectAITaskExecutionResult] = []
        for task_plan in plan.tasks:
            spec = specs[task_plan.task_id]
            candidate_keys = {(item.provider, item.model) for item in task_plan.candidates}
            candidate_models = tuple(
                model
                for model in self.models
                if (model.provider, model.model) in candidate_keys
            )
            platform = self._platform(transports, models=candidate_models)
            platform.policy.allowed_by_project[scope.policy_scope] = {
                item.provider for item in task_plan.candidates
            }
            layer = AIRoutingLayer(platform)
            policy = RoutingPolicy(
                optimization=spec.optimization,
                execution=ExecutionMode.SINGLE,
                max_models=1,
                allow_failover=bool(task_plan.fallbacks),
                offline_only=spec.require_local,
                privacy_mode=spec.sensitivity == DataSensitivity.RESTRICTED,
                provider_priority=tuple(item.provider for item in task_plan.candidates),
            )
            routed = await layer.execute(
                spec.model_request(),
                policy,
                project=scope.policy_scope,
                budget_scope=scope.budget_scope,
            )
            chosen = routed.selected
            chosen_evidence = self._model_by_key[(chosen.provider, chosen.model)]
            primary = task_plan.primary
            results.append(
                ProjectAITaskExecutionResult(
                    task_id=task_plan.task_id,
                    role=task_plan.role,
                    provider=chosen.provider,
                    model=chosen.model,
                    text=chosen.text,
                    cost_usd=chosen.cost,
                    latency_ms=chosen.latency_ms,
                    fallback_used=(chosen.provider, chosen.model)
                    != (primary.provider, primary.model),
                    attempted_routes=tuple(
                        f"{item.decision.provider}/{item.decision.model}"
                        for item in routed.candidates
                    ),
                    evidence_ref=chosen_evidence.evidence_ref,
                )
            )
        return tuple(results)
