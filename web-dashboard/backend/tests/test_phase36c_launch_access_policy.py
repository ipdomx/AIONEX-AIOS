"""Phase 36C launch Free/Paid/Owner provider entitlement contracts."""
from __future__ import annotations

from uuid import uuid4

import pytest

from app.db.base import SessionLocal
from sqlalchemy import delete

from app.db.models import BillingAccount, BillingPlan, Organization, OwnerControlRecord, User
from app.services.project_ai_access_policy import (
    PLAN_POLICY_DOMAIN,
    USER_POLICY_DOMAIN,
    ProjectAIAccessPolicyError,
    default_plan_policy,
    resolve_project_ai_access,
)




async def _clear_launch_policy_records(session) -> None:
    await session.execute(
        delete(OwnerControlRecord).where(
            OwnerControlRecord.domain.in_({PLAN_POLICY_DOMAIN, USER_POLICY_DOMAIN})
        )
    )
    await session.commit()


def test_free_default_is_local_zero_cost_and_paid_default_fails_until_owner_selects_models() -> None:
    free = default_plan_policy("free")
    paid = default_plan_policy("paid")
    assert free["allowed_provider_models"] == ["ollama:gemma3:4b"]
    assert free["max_project_cost_usd"] == 0.0
    assert free["offline_only"] is True
    assert paid["allowed_provider_models"] == []
    assert paid["max_project_cost_usd"] > 0


async def _seed_consumer(*, plan_code: str) -> tuple[str, str]:
    suffix = uuid4().hex[:10]
    org_id = f"launch-org-{suffix}"
    user_id = f"launch-user-{suffix}"
    async with SessionLocal() as session:
        plan = BillingPlan(
            code=f"{plan_code}-{suffix}",
            name=f"{plan_code} test",
            status="active",
            default_currency="USD",
            limits={},
            entitlements=[],
            metering={},
            source_version=1,
            source_hash="a" * 64,
        )
        # Exact `free` needs the canonical code so use organization fallback path
        # rather than conflicting with a shared seeded BillingPlan in parallel tests.
        org = Organization(id=org_id, name="Launch tenant", slug=org_id, plan=plan_code, status="active")
        user = User(
            id=user_id,
            organization_id=org_id,
            role_id=None,
            email=f"{user_id}@example.com",
            name="Launch User",
            password_hash="unused",
            status="active",
        )
        session.add_all([org, user])
        if plan_code != "free":
            session.add(plan)
            await session.flush()
            session.add(BillingAccount(
                organization_id=org_id,
                plan_id=plan.id,
                status="active",
                licensed_seats=1,
                limits={},
                entitlements=[],
            ))
        await session.commit()
    return org_id, user_id


@pytest.mark.asyncio
async def test_free_consumer_resolves_platform_ollama_without_copying_provider_credentials() -> None:
    org_id, user_id = await _seed_consumer(plan_code="free")
    async with SessionLocal() as session:
        access = await resolve_project_ai_access(session, organization_id=org_id, user_id=user_id)
        assert access.access_class == "free"
        assert access.policy.provider_scope_organization_id == "aionex-org"
        assert access.policy.allowed_providers == frozenset({"ollama"})
        assert access.policy.allowed_provider_models == frozenset({"ollama:gemma3:4b"})
        assert access.policy.max_total_estimated_cost_usd == 0


@pytest.mark.asyncio
async def test_paid_consumer_fails_closed_until_owner_selects_current_validated_models() -> None:
    org_id, user_id = await _seed_consumer(plan_code="enterprise")
    async with SessionLocal() as session:
        await _clear_launch_policy_records(session)
        with pytest.raises(ProjectAIAccessPolicyError, match="no approved provider models"):
            await resolve_project_ai_access(session, organization_id=org_id, user_id=user_id)


@pytest.mark.asyncio
async def test_owner_paid_plan_and_per_user_override_control_exact_provider_model_consumption() -> None:
    org_id, user_id = await _seed_consumer(plan_code="enterprise")
    async with SessionLocal() as session:
        await _clear_launch_policy_records(session)
        session.add(OwnerControlRecord(
            domain=PLAN_POLICY_DOMAIN,
            resource_id="paid",
            status="active",
            enabled=True,
            payload={
                "access_class": "paid",
                "allowed_provider_models": ["openai:gpt-current-paid"],
                "max_project_cost_usd": 2.0,
                "max_fallbacks": 1,
            },
        ))
        await session.commit()
        plan_access = await resolve_project_ai_access(session, organization_id=org_id, user_id=user_id)
        assert plan_access.source == "plan:paid"
        assert plan_access.policy.allowed_provider_models == frozenset({"openai:gpt-current-paid"})

        session.add(OwnerControlRecord(
            domain=USER_POLICY_DOMAIN,
            resource_id=user_id,
            status="active",
            enabled=True,
            payload={
                "access_class": "paid",
                "allowed_provider_models": ["gemini:gemini-current-paid"],
                "max_project_cost_usd": 1.0,
                "max_fallbacks": 0,
            },
        ))
        await session.commit()
        user_access = await resolve_project_ai_access(session, organization_id=org_id, user_id=user_id)
        assert user_access.source == f"user:{user_id}"
        assert user_access.policy.allowed_provider_models == frozenset({"gemini:gemini-current-paid"})
        assert user_access.policy.allowed_providers == frozenset({"gemini"})


def test_free_policy_rejects_external_paid_provider() -> None:
    from app.services.project_ai_access_policy import _normalize_payload
    with pytest.raises(ProjectAIAccessPolicyError, match="free policy may only use"):
        _normalize_payload({
            "access_class": "free",
            "allowed_provider_models": ["openai:gpt-5.6-sol"],
            "max_project_cost_usd": 0,
        }, expected_class="free")

@pytest.mark.asyncio
async def test_durable_resolver_reads_only_explicit_platform_provider_model_grant() -> None:
    from datetime import UTC, datetime, timedelta

    from app.db.models import AIProvider, Project, ProjectExecution, Workspace
    from app.services.project_execution_routing import ProjectAIScope
    from app.services.project_execution_routing_durable import DurableProjectAIResolver

    suffix = uuid4().hex[:10]
    org_id = f"consumer-org-{suffix}"
    user_id = f"consumer-user-{suffix}"
    workspace_id = f"consumer-ws-{suffix}"
    project_id = f"consumer-project-{suffix}"
    execution_id = f"consumer-exec-{suffix}"
    provider_id = f"platform-provider-{suffix}"
    current = datetime.now(UTC)
    async with SessionLocal() as session:
        await session.execute(delete(AIProvider).where(AIProvider.id.like("platform-provider-%")))
        await session.commit()
        platform_org = await session.get(Organization, "aionex-org")
        if platform_org is None:
            session.add(Organization(
                id="aionex-org",
                name="AIONEX Platform",
                slug=f"aionex-platform-{suffix}",
                plan="enterprise",
                status="active",
            ))
        session.add_all([
            Organization(id=org_id, name="Consumer", slug=org_id, plan="free", status="active"),
            User(
                id=user_id,
                organization_id=org_id,
                role_id=None,
                email=f"{user_id}@example.com",
                name="Consumer",
                password_hash="unused",
                status="active",
            ),
            Workspace(
                id=workspace_id,
                organization_id=org_id,
                name="Consumer workspace",
                slug=workspace_id,
                status="active",
            ),
        ])
        await session.flush()
        session.add(Project(
            id=project_id,
            organization_id=org_id,
            workspace_id=workspace_id,
            owner_id=user_id,
            name="Consumer project",
            slug=project_id,
            status="planning",
            priority="medium",
            progress=0,
            tags=[],
        ))
        session.add(AIProvider(
            id=provider_id,
            organization_id="aionex-org",
            name="Platform Ollama",
            type="ollama",
            status="connected",
            base_url="http://ollama:11434",
            encrypted_api_key=None,
            config={
                "enabled": True,
                "validated_models": [
                    {
                        "model": "gemma3:4b",
                        "tasks": ["reasoning", "coding"],
                        "evidence_ref": "test:ollama:current",
                        "policy_ref": "test:free:v1",
                        "validated_at": current.isoformat(),
                        "expires_at": (current + timedelta(hours=1)).isoformat(),
                        "languages": ["multilingual"],
                        "local": True,
                        "max_context_tokens": 8192,
                        "quality_score": 0.6,
                        "latency_score": 0.5,
                        "privacy_score": 1.0,
                        "input_cost_per_million": 0.0,
                        "output_cost_per_million": 0.0,
                        "requests_per_minute": 60,
                        "concurrent_requests": 2,
                        "circuit_failure_threshold": 3,
                        "circuit_failure_window_seconds": 60,
                        "circuit_open_seconds": 30,
                        "lease_seconds": 120,
                    },
                    {
                        "model": "other-local-model",
                        "tasks": ["reasoning"],
                        "evidence_ref": "test:ollama:other",
                        "policy_ref": "test:other:v1",
                        "validated_at": current.isoformat(),
                        "expires_at": (current + timedelta(hours=1)).isoformat(),
                        "languages": ["multilingual"],
                        "local": True,
                        "max_context_tokens": 8192,
                        "quality_score": 0.5,
                        "latency_score": 0.5,
                        "privacy_score": 1.0,
                        "input_cost_per_million": 0.0,
                        "output_cost_per_million": 0.0,
                        "requests_per_minute": 60,
                        "concurrent_requests": 2,
                        "circuit_failure_threshold": 3,
                        "circuit_failure_window_seconds": 60,
                        "circuit_open_seconds": 30,
                        "lease_seconds": 120,
                    },
                ],
            },
        ))
        session.add(ProjectExecution(
            id=execution_id,
            organization_id=org_id,
            workspace_id=workspace_id,
            project_id=project_id,
            requested_by_id=user_id,
            mode="full",
            provider="policy",
            status="completed",
            stage="evidence_fixture",
            progress=100,
            objective="Build a tenant-safe live project with the free provider.",
            external_processing_confirmed=True,
            budget_cap_usd=0.0,
            result_summary={},
            resource_class="project-build-cpu",
            priority_rank=200,
            attempts=0,
            max_attempts=3,
            review_status="not_requested",
            rework_count=0,
            version=1,
        ))
        await session.commit()
        access = await resolve_project_ai_access(session, organization_id=org_id, user_id=user_id)
        resolved = await DurableProjectAIResolver(session).resolve(
            ProjectAIScope(
                organization_id=org_id,
                workspace_id=workspace_id,
                project_id=project_id,
                execution_id=execution_id,
            ),
            access.policy,
            now=current,
        )
        assert [(item.provider_type, item.route_model.model) for item in resolved] == [
            ("ollama", "gemma3:4b")
        ]
        assert resolved[0].provider_id == provider_id


def test_owner_project_ai_policy_routes_are_materialized_in_public_api_router() -> None:
    from fastapi import FastAPI
    from fastapi.routing import APIRoute

    from app.api.v1.router import api_router

    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    routes: set[tuple[str, str]] = set()
    for candidate in app.routes:
        contexts = getattr(candidate, "effective_route_contexts", None)
        if callable(contexts):
            effective = [row for row in contexts() if getattr(row, "dependant", None) is not None]
        elif isinstance(candidate, APIRoute):
            effective = [candidate]
        else:
            effective = []
        for route in effective:
            for method in route.methods:
                routes.add((method, route.path))
    expected = {
        ("GET", "/api/v1/owner/project-ai/access"),
        ("PUT", "/api/v1/owner/project-ai/access/plans/{access_class}"),
        ("PUT", "/api/v1/owner/project-ai/access/users/{user_id}"),
        ("DELETE", "/api/v1/owner/project-ai/access/users/{user_id}"),
        ("GET", "/api/v1/owner/project-ai/providers/{provider_id}/finance"),
        ("PUT", "/api/v1/owner/project-ai/providers/{provider_id}/finance"),
    }
    assert expected <= routes
