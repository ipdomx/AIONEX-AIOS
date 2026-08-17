"""Phase 36C production live-runtime adapter contracts without provider network calls."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import delete

from app.db.base import SessionLocal
from app.db.models import AIProvider, Organization
from app.services import project_ai_live_runtime as live
from app.services.project_execution_ai_integration import (
    ProjectAIInvocation,
    ProjectAIInvocationFailure,
)
from app.services.project_execution_routing import ProjectAIProviderPolicy, ProjectAIScope


async def _seed_provider(provider_type: str = "mistral", model: str = "mistral-medium-3-5") -> tuple[str, str, str]:
    suffix = uuid4().hex[:8]
    org_id = f"live-runtime-org-{suffix}"
    provider_id = f"live-provider-{suffix}"
    evidence_ref = f"live-evidence-{suffix}"
    now = datetime.now(UTC)
    async with SessionLocal() as session:
        session.add(Organization(id=org_id, name="Live Runtime", slug=org_id, plan="enterprise", status="active"))
        await session.flush()
        session.add(
            AIProvider(
                id=provider_id,
                organization_id=org_id,
                name="Live Provider",
                type=provider_type,
                status="connected",
                config={
                    "enabled": True,
                    "validated_models": [
                        {
                            "model": model,
                            "tasks": ["reasoning", "coding"],
                            "evidence_ref": evidence_ref,
                            "policy_ref": "test:live:v1",
                            "validated_at": (now - timedelta(minutes=1)).isoformat(),
                            "expires_at": (now + timedelta(hours=1)).isoformat(),
                            "input_cost_per_million": 1.5,
                            "output_cost_per_million": 7.5,
                        }
                    ],
                },
            )
        )
        await session.commit()
    return org_id, provider_id, evidence_ref


def _invocation(org_id: str, provider_id: str, evidence_ref: str) -> ProjectAIInvocation:
    return ProjectAIInvocation(
        scope=ProjectAIScope(
            organization_id=org_id,
            workspace_id="workspace",
            project_id="project",
            execution_id="execution",
        ),
        task_id="coder",
        role="coder",
        task="coding",
        provider_id=provider_id,
        provider="mistral",
        model="mistral-medium-3-5",
        evidence_ref=evidence_ref,
        prompt="build the project",
        system_prompt="",
        memory=(),
    )


@pytest.mark.asyncio
async def test_live_invoker_reuses_runtime_adapter_and_computes_cost_from_validated_model(monkeypatch) -> None:
    org_id, provider_id, evidence_ref = await _seed_provider()

    async def fake_execute(_provider, agent, prompt):
        assert agent.model == "mistral-medium-3-5"
        assert prompt == "build the project"
        return {
            "text": "complete",
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            "latency_ms": 12.5,
        }

    monkeypatch.setattr(live, "_execute_provider", fake_execute)
    try:
        result = await live.ProjectAILiveProviderInvoker()( _invocation(org_id, provider_id, evidence_ref) )
        assert result.text == "complete"
        assert result.input_tokens == 100
        assert result.output_tokens == 50
        assert result.cost_usd == 0.000525
        assert result.memory_note == "mistral:mistral-medium-3-5:coder:completed"
    finally:
        async with SessionLocal() as session:
            await session.execute(delete(Organization).where(Organization.id == org_id))
            await session.commit()


@pytest.mark.asyncio
async def test_live_invoker_rejects_evidence_mismatch_before_provider_call(monkeypatch) -> None:
    org_id, provider_id, _ = await _seed_provider()
    called = False

    async def fake_execute(*_args, **_kwargs):
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(live, "_execute_provider", fake_execute)
    try:
        with pytest.raises(ProjectAIInvocationFailure, match="provider_model_evidence_invalid"):
            await live.ProjectAILiveProviderInvoker()( _invocation(org_id, provider_id, "wrong-evidence") )
        assert called is False
    finally:
        async with SessionLocal() as session:
            await session.execute(delete(Organization).where(Organization.id == org_id))
            await session.commit()


@pytest.mark.asyncio
async def test_live_invoker_maps_quota_failure_and_notifies_owner(monkeypatch) -> None:
    org_id, provider_id, evidence_ref = await _seed_provider()
    alerts: list[tuple[str, bool]] = []

    async def fake_execute(*_args, **_kwargs):
        raise HTTPException(status_code=502, detail="Provider returned HTTP 429")

    async def fake_alert(_session, *, provider_id: str, failure_code: str, critical: bool):
        alerts.append((failure_code, critical))
        return []

    async def fake_publish(_notifications):
        return None

    monkeypatch.setattr(live, "_execute_provider", fake_execute)
    monkeypatch.setattr(live, "notify_provider_billing_failure", fake_alert)
    monkeypatch.setattr(live.communications, "publish_many", fake_publish)
    try:
        with pytest.raises(ProjectAIInvocationFailure, match="provider_quota"):
            await live.ProjectAILiveProviderInvoker()( _invocation(org_id, provider_id, evidence_ref) )
        assert alerts == [("provider_quota", False)]
    finally:
        async with SessionLocal() as session:
            await session.execute(delete(Organization).where(Organization.id == org_id))
            await session.commit()


def test_launch_policy_task_factory_disables_tool_requirement_for_free_local_policy() -> None:
    free = ProjectAIProviderPolicy(
        allowed_providers=frozenset({"ollama"}),
        allowed_provider_models=frozenset({"ollama:gemma3:4b"}),
        max_fallbacks=0,
        offline_only=True,
        privacy_mode=True,
        max_total_estimated_cost_usd=0.0,
    )
    paid = ProjectAIProviderPolicy(
        allowed_providers=frozenset({"mistral", "deepseek"}),
        allowed_provider_models=frozenset({"mistral:mistral-medium-3-5", "deepseek:deepseek-v4-pro"}),
        max_fallbacks=1,
    )
    free_tasks = live.launch_policy_tasks("Free project", "Build a complete project safely", free)
    paid_tasks = live.launch_policy_tasks("Paid project", "Build a complete project safely", paid)
    free_coder = next(task for task in free_tasks if task.role == "coder")
    paid_coder = next(task for task in paid_tasks if task.role == "coder")
    assert free_coder.require_tools is False
    assert free_coder.allow_failover is False
    assert free_coder.max_fallbacks == 0
    assert paid_coder.require_tools is True
    assert paid_coder.allow_failover is True
    assert paid_coder.max_fallbacks == 1
