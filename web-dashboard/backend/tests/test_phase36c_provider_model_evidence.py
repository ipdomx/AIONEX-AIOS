"""Phase 36C provider model inventory/execution evidence contracts."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.db.base import SessionLocal
from app.db.models import AIProvider, AuditEvent, Organization
from app.services.provider_model_evidence import (
    ProviderModelEvidenceError,
    ProviderModelExecutionEvidence,
    ProviderModelInventoryEvidence,
    ProviderModelValidationSpec,
    build_validated_model_from_execution,
    build_validated_model_from_inventory,
    parse_provider_model_inventory,
    persist_provider_validated_model,
    probe_provider_model_inventory,
)


def _spec(provider: str, model: str, *, tasks: frozenset[str] | None = None) -> ProviderModelValidationSpec:
    return ProviderModelValidationSpec(
        provider_type=provider,
        model=model,
        tasks=tasks or frozenset({"reasoning", "research", "coding", "review"}),
        policy_ref=f"phase36c:test-policy:{provider}:{model}",
        languages=frozenset({"en", "ar"}),
        supports_tools=True,
        max_context_tokens=32768,
        quality_score=0.8,
        latency_score=0.8,
        privacy_score=0.7,
        input_cost_per_million=1.0,
        output_cost_per_million=2.0,
        requests_per_minute=60,
        concurrent_requests=2,
        circuit_failure_threshold=3,
        circuit_failure_window_seconds=60,
        circuit_open_seconds=60,
        lease_seconds=30,
    )


def test_inventory_parsers_are_provider_specific_and_reject_placeholders() -> None:
    assert parse_provider_model_inventory("openai", {"data": [{"id": "gpt-test"}]}) == ("gpt-test",)
    assert parse_provider_model_inventory("gemini", {"models": [{"name": "models/gemini-test"}]}) == ("gemini-test",)
    assert parse_provider_model_inventory("ollama", {"models": [{"name": "gemma-test:latest"}]}) == ("gemma-test:latest",)
    assert parse_provider_model_inventory("together", [{"id": "meta/test"}]) == ("meta/test",)
    with pytest.raises(ProviderModelEvidenceError, match="not valid live evidence"):
        parse_provider_model_inventory("openai", {"data": [{"id": "default"}]})
    with pytest.raises(ProviderModelEvidenceError, match="requires execution evidence"):
        parse_provider_model_inventory("anthropic", {"data": [{"id": "claude-test"}]})


@pytest.mark.asyncio
async def test_inventory_probe_uses_injected_requester_and_never_needs_real_network() -> None:
    provider = AIProvider(
        id="provider-openai-test",
        organization_id="org-test",
        name="OpenAI Test",
        type="openai",
        status="connected",
        encrypted_api_key=None,
        base_url="https://api.openai.com",
        config={"enabled": True, "credential_source": "environment"},
    )
    calls = []

    async def requester(method, url, *, headers, timeout, allow_array=False, **_kwargs):
        calls.append((method, url, bool(headers.get("Authorization")), timeout, allow_array))
        return {"data": [{"id": "gpt-test"}, {"id": "gpt-test-2"}]}, 12.5

    # Avoid reading a real environment credential in this deterministic contract.
    from app.services import provider_model_evidence as module
    original = module.provider_credential
    module.provider_credential = lambda _provider: "synthetic-test-credential"
    try:
        evidence = await probe_provider_model_inventory(
            provider,
            requester=requester,
            observed_at=datetime(2026, 8, 17, 12, 0, tzinfo=UTC),
        )
    finally:
        module.provider_credential = original
    assert evidence.model_ids == ("gpt-test", "gpt-test-2")
    assert evidence.latency_ms == 12.5
    assert evidence.evidence_ref.startswith("phase36c:provider-model-inventory:")
    assert calls == [("GET", "https://api.openai.com/v1/models", True, 30.0, False)]


@pytest.mark.asyncio
async def test_inventory_probe_refuses_execution_only_provider() -> None:
    provider = AIProvider(
        id="provider-anthropic-test",
        organization_id="org-test",
        name="Anthropic Test",
        type="anthropic",
        status="connected",
        encrypted_api_key=None,
        base_url="https://api.anthropic.com",
        config={"enabled": True, "credential_source": "environment"},
    )
    with pytest.raises(ProviderModelEvidenceError, match="bounded execution evidence"):
        await probe_provider_model_inventory(provider)


def test_inventory_evidence_requires_current_exact_model_and_explicit_policy() -> None:
    observed = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
    evidence = ProviderModelInventoryEvidence(
        provider_id="p1",
        provider_type="openai",
        model_ids=("gpt-test",),
        evidence_ref="phase36c:test-inventory",
        observed_at=observed,
        latency_ms=10,
    )
    entry = build_validated_model_from_inventory(
        evidence,
        _spec("openai", "gpt-test"),
        now=observed + timedelta(minutes=5),
        ttl=timedelta(hours=6),
    )
    assert entry["model"] == "gpt-test"
    assert entry["tasks"] == ["coding", "reasoning", "research", "review"]
    assert entry["policy_ref"].startswith("phase36c:test-policy:")
    assert entry["evidence_ref"].startswith("phase36c:test-inventory:")
    with pytest.raises(ProviderModelEvidenceError, match="absent"):
        build_validated_model_from_inventory(
            evidence, _spec("openai", "gpt-missing"), now=observed + timedelta(minutes=5)
        )
    with pytest.raises(ProviderModelEvidenceError, match="stale"):
        build_validated_model_from_inventory(
            evidence, _spec("openai", "gpt-test"), now=observed + timedelta(hours=2)
        )


def test_execution_evidence_is_required_for_anthropic_cohere_bedrock() -> None:
    observed = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
    evidence = ProviderModelExecutionEvidence(
        provider_id="anthropic-1",
        provider_type="anthropic",
        model="claude-test",
        passed_tasks=frozenset({"reasoning", "research", "coding", "review"}),
        evidence_ref="phase36c:test-execution",
        observed_at=observed,
    )
    entry = build_validated_model_from_execution(
        evidence,
        _spec("anthropic", "claude-test"),
        now=observed + timedelta(minutes=1),
    )
    assert entry["model"] == "claude-test"
    with pytest.raises(ProviderModelEvidenceError, match="did not pass every required task"):
        build_validated_model_from_execution(
            ProviderModelExecutionEvidence(
                provider_id="anthropic-1",
                provider_type="anthropic",
                model="claude-test",
                passed_tasks=frozenset({"reasoning"}),
                evidence_ref="phase36c:test-execution-small",
                observed_at=observed,
            ),
            _spec("anthropic", "claude-test"),
            now=observed + timedelta(minutes=1),
        )


async def _seed_provider(suffix: str) -> tuple[str, str]:
    org = Organization(
        id=f"p36c-evidence-org-{suffix}",
        name=f"P36C Evidence {suffix}",
        slug=f"p36c-evidence-{suffix}",
        plan="enterprise",
        status="active",
    )
    provider = AIProvider(
        id=f"p36c-evidence-provider-{suffix}",
        organization_id=org.id,
        name="Evidence Provider",
        type="openai",
        status="connected",
        encrypted_api_key=None,
        base_url="https://api.openai.com",
        config={"enabled": True, "credential_source": "environment"},
    )
    async with SessionLocal() as session:
        session.add(org)
        await session.flush()
        session.add(provider)
        await session.commit()
    return org.id, provider.id


async def _cleanup_org(org_id: str) -> None:
    async with SessionLocal() as session:
        await session.execute(delete(AuditEvent).where(AuditEvent.organization_id == org_id))
        await session.execute(delete(AIProvider).where(AIProvider.organization_id == org_id))
        await session.execute(delete(Organization).where(Organization.id == org_id))
        await session.commit()


@pytest.mark.asyncio
async def test_persistence_is_tenant_scoped_idempotent_and_prompt_free() -> None:
    suffix = uuid4().hex[:8]
    org_id, provider_id = await _seed_provider(suffix)
    now = datetime.now(UTC)
    entry = _spec("openai", "gpt-test").validated_entry(
        evidence_ref="phase36c:test-evidence",
        validated_at=now,
        ttl=timedelta(hours=1),
    )
    entry["provider_type"] = "openai"
    try:
        async with SessionLocal() as session:
            await persist_provider_validated_model(
                session,
                organization_id=org_id,
                provider_id=provider_id,
                actor_id=None,
                entry=entry,
            )
            await session.commit()
        async with SessionLocal() as session:
            # Replace the same model instead of duplicating it.
            await persist_provider_validated_model(
                session,
                organization_id=org_id,
                provider_id=provider_id,
                actor_id=None,
                entry=entry,
            )
            await session.commit()
            provider = await session.get(AIProvider, provider_id)
            audits = list(
                (
                    await session.scalars(
                        select(AuditEvent).where(
                            AuditEvent.organization_id == org_id,
                            AuditEvent.action == "provider.model_evidence.validated",
                        )
                    )
                ).all()
            )
            assert provider is not None
            rows = provider.config["validated_models"]
            assert len(rows) == 1 and rows[0]["model"] == "gpt-test"
            assert len(audits) == 2
            rendered = repr([item.details for item in audits]).lower()
            assert "prompt" not in rendered
            assert "credential" not in rendered
        with pytest.raises(ProviderModelEvidenceError, match="not found"):
            async with SessionLocal() as session:
                await persist_provider_validated_model(
                    session,
                    organization_id="other-org",
                    provider_id=provider_id,
                    actor_id=None,
                    entry=entry,
                )
    finally:
        await _cleanup_org(org_id)
