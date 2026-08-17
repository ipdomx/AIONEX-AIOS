from __future__ import annotations

import json

import pytest

from aios.providers import DataSensitivity, ModelResponse, OptimizationMode
from app.services.project_execution_routing import (
    ProjectAIProviderPolicy,
    ProjectAIRoutePlanner,
    ProjectAIRoutingError,
    ProjectAIScope,
    ProjectAITaskSpec,
    ValidatedProviderModel,
)


def model(
    provider: str,
    runtime_model: str,
    tasks: set[str],
    *,
    local: bool = False,
    quality: float = 0.8,
    latency: float = 0.7,
    privacy: float = 0.6,
    input_cost: float = 1.0,
    output_cost: float = 2.0,
) -> ValidatedProviderModel:
    return ValidatedProviderModel(
        provider=provider,
        model=runtime_model,
        tasks=frozenset(tasks),
        evidence_ref=f"test-evidence:{provider}:{runtime_model}",
        local=local,
        quality_score=quality,
        latency_score=latency,
        privacy_score=privacy,
        input_cost_per_million=input_cost,
        output_cost_per_million=output_cost,
    )


def scope(organization: str = "org-a") -> ProjectAIScope:
    return ProjectAIScope(
        organization_id=organization,
        workspace_id="workspace-shared",
        project_id="project-shared",
        execution_id="execution-shared",
    )


def coding_task(**overrides) -> ProjectAITaskSpec:
    payload = {
        "task_id": "task-coder",
        "role": "coder",
        "task": "coding",
        "prompt": "TOP_SECRET_PROMPT_36C build the module",
        "system_prompt": "TOP_SECRET_SYSTEM_36C internal policy",
        "provider_priority": ("openai", "anthropic"),
        "max_fallbacks": 1,
    }
    payload.update(overrides)
    return ProjectAITaskSpec(**payload)


def test_route_plan_is_tenant_scoped_and_prompt_free() -> None:
    planner = ProjectAIRoutePlanner(
        (
            model("openai", "gpt-test-2026", {"coding"}, quality=0.95),
            model("anthropic", "claude-test-2026", {"coding"}, quality=0.9),
        )
    )
    policy = ProjectAIProviderPolicy(
        allowed_providers=frozenset({"openai", "anthropic"})
    )
    first = planner.plan(scope("org-a"), (coding_task(),), policy)
    second = planner.plan(scope("org-b"), (coding_task(),), policy)

    assert first.scope.policy_scope != second.scope.policy_scope
    assert first.scope.budget_scope != second.scope.budget_scope
    assert first.tasks[0].primary.provider == "openai"
    evidence = json.dumps(first.evidence(), sort_keys=True)
    assert "TOP_SECRET_PROMPT_36C" not in evidence
    assert "TOP_SECRET_SYSTEM_36C" not in evidence
    assert "org-a" in evidence
    assert "gpt-test-2026" in evidence


def test_live_route_plan_rejects_default_model_alias_and_implicit_provider_policy() -> None:
    with pytest.raises(ValueError, match="default model aliases"):
        model("openai", "default", {"coding"})
    with pytest.raises(ValueError, match="allowed_providers"):
        ProjectAIProviderPolicy(allowed_providers=frozenset())


def test_restricted_task_routes_local_and_never_lists_remote_fallback() -> None:
    planner = ProjectAIRoutePlanner(
        (
            model("openai", "gpt-test-2026", {"coding"}, quality=0.99),
            model(
                "ollama",
                "qwen-test-local",
                {"coding"},
                local=True,
                quality=0.7,
                privacy=1.0,
                input_cost=0,
                output_cost=0,
            ),
        )
    )
    plan = planner.plan(
        scope(),
        (
            coding_task(
                sensitivity=DataSensitivity.RESTRICTED,
                provider_priority=("openai", "ollama"),
                max_fallbacks=2,
            ),
        ),
        ProjectAIProviderPolicy(
            allowed_providers=frozenset({"openai", "ollama"})
        ),
    )
    task_plan = plan.tasks[0]
    assert task_plan.primary.provider == "ollama"
    assert task_plan.primary.local is True
    assert task_plan.fallbacks == ()


@pytest.mark.asyncio
async def test_deterministic_adapter_uses_only_approved_fallback_and_exact_model_evidence() -> None:
    async def openai_down(request, runtime_model):
        raise ConnectionError("simulated-openai-outage")

    async def anthropic_ok(request, runtime_model):
        return ModelResponse(
            provider="anthropic",
            model=runtime_model,
            text="deterministic-fallback-success",
            input_tokens=10,
            output_tokens=5,
            cost=0.002,
            latency_ms=12.0,
            confidence=0.95,
        )

    planner = ProjectAIRoutePlanner(
        (
            model("openai", "gpt-test-2026", {"coding"}, quality=0.95),
            model("anthropic", "claude-test-2026", {"coding"}, quality=0.9),
        )
    )
    task = coding_task(provider_priority=("openai", "anthropic"), allow_failover=True)
    plan = planner.plan(
        scope(),
        (task,),
        ProjectAIProviderPolicy(
            allowed_providers=frozenset({"openai", "anthropic"})
        ),
    )
    assert plan.tasks[0].primary.provider == "openai"
    assert [item.provider for item in plan.tasks[0].fallbacks] == ["anthropic"]

    result = (
        await planner.execute_deterministic(
            scope(),
            plan,
            (task,),
            {"openai": openai_down, "anthropic": anthropic_ok},
        )
    )[0]
    assert result.provider == "anthropic"
    assert result.model == "claude-test-2026"
    assert result.fallback_used is True
    assert result.attempted_routes == (
        "openai/gpt-test-2026",
        "anthropic/claude-test-2026",
    )
    assert result.evidence_ref == "test-evidence:anthropic:claude-test-2026"
    assert result.text == "deterministic-fallback-success"
    rendered = json.dumps(result.evidence(), sort_keys=True)
    assert "TOP_SECRET_PROMPT_36C" not in rendered
    assert "deterministic-fallback-success" not in rendered


@pytest.mark.asyncio
async def test_no_fallback_policy_fails_closed_when_primary_is_unavailable() -> None:
    async def openai_down(request, runtime_model):
        raise ConnectionError("simulated-openai-outage")

    async def anthropic_ok(request, runtime_model):
        return ModelResponse(
            provider="anthropic",
            model=runtime_model,
            text="must-not-run",
            confidence=1.0,
        )

    planner = ProjectAIRoutePlanner(
        (
            model("openai", "gpt-test-2026", {"coding"}, quality=0.95),
            model("anthropic", "claude-test-2026", {"coding"}, quality=0.9),
        )
    )
    task = coding_task(allow_failover=False, provider_priority=("openai", "anthropic"))
    plan = planner.plan(
        scope(),
        (task,),
        ProjectAIProviderPolicy(
            allowed_providers=frozenset({"openai", "anthropic"})
        ),
    )
    assert plan.tasks[0].fallbacks == ()
    with pytest.raises(RuntimeError, match="all routed model calls failed"):
        await planner.execute_deterministic(
            scope(),
            plan,
            (task,),
            {"openai": openai_down, "anthropic": anthropic_ok},
        )


def test_tenant_provider_allowlist_and_budget_ceiling_fail_closed() -> None:
    planner = ProjectAIRoutePlanner(
        (
            model("openai", "gpt-test-2026", {"coding"}, quality=0.95),
            model("anthropic", "claude-test-2026", {"coding"}, quality=0.9),
        )
    )
    anthropic_only = planner.plan(
        scope(),
        (coding_task(provider_priority=("openai", "anthropic")),),
        ProjectAIProviderPolicy(allowed_providers=frozenset({"anthropic"})),
    )
    assert anthropic_only.tasks[0].primary.provider == "anthropic"

    with pytest.raises(ProjectAIRoutingError, match="budget ceiling"):
        planner.plan(
            scope(),
            (coding_task(),),
            ProjectAIProviderPolicy(
                allowed_providers=frozenset({"openai", "anthropic"}),
                max_total_estimated_cost_usd=0.0,
            ),
        )


def test_budget_ceiling_selects_highest_ranked_affordable_route() -> None:
    planner = ProjectAIRoutePlanner(
        (
            model(
                "openai",
                "gpt-expensive",
                {"coding"},
                quality=0.99,
                latency=0.95,
                input_cost=20.0,
                output_cost=100.0,
            ),
            model(
                "anthropic",
                "claude-affordable",
                {"coding"},
                quality=0.70,
                latency=0.70,
                input_cost=0.5,
                output_cost=1.0,
            ),
        )
    )
    task = coding_task(
        optimization=OptimizationMode.QUALITY,
        max_tokens=1000,
        allow_failover=False,
        provider_priority=("openai", "anthropic"),
    )
    unbounded = planner.plan(
        scope(),
        (task,),
        ProjectAIProviderPolicy(
            allowed_providers=frozenset({"openai", "anthropic"})
        ),
    )
    assert unbounded.tasks[0].primary.provider == "openai"

    bounded = planner.plan(
        scope(),
        (task,),
        ProjectAIProviderPolicy(
            allowed_providers=frozenset({"openai", "anthropic"}),
            max_total_estimated_cost_usd=0.005,
        ),
    )
    assert bounded.tasks[0].primary.provider == "anthropic"
    assert bounded.total_primary_estimated_cost_usd <= 0.005


def test_duplicate_task_ids_are_rejected_before_routing() -> None:
    planner = ProjectAIRoutePlanner(
        (model("openai", "gpt-test-2026", {"coding", "review"}),)
    )
    with pytest.raises(ProjectAIRoutingError, match="task ids must be unique"):
        planner.plan(
            scope(),
            (
                coding_task(),
                ProjectAITaskSpec(
                    task_id="task-coder",
                    role="reviewer",
                    task="review",
                    prompt="review without leaking prompt into evidence",
                ),
            ),
            ProjectAIProviderPolicy(allowed_providers=frozenset({"openai"})),
        )
