"""Durable AI runtime regression tests."""
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.db.base import SessionLocal
from app.db.models import AIAgent, AIProvider, AuditEvent, Job, Notification, Organization, User
from app.db.seed import seed
from app.services import ai_runtime_service


@pytest.mark.asyncio
async def test_provider_agent_job_and_notification_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    await seed()
    suffix = uuid4().hex[:12]
    provider_id: str | None = None
    agent_id: str | None = None
    job_id: str | None = None

    async def fake_execute(provider: AIProvider, agent: AIAgent, prompt: str) -> dict[str, object]:
        assert provider.type == "openai"
        assert agent.model == "test-model"
        assert prompt == "verify durable runtime execution"
        return {
            "text": "verified provider response",
            "provider": provider.type,
            "model": agent.model,
            "usage": {"input_tokens": 3, "output_tokens": 4, "total_tokens": 7},
            "cost": 0.0007,
            "latency_ms": 12.0,
            "response_id": "response-test",
        }

    monkeypatch.setattr(ai_runtime_service, "_execute_provider", fake_execute)

    try:
        async with SessionLocal() as session:
            organization = await session.get(Organization, "aionex-org")
            assert organization is not None
            owner = await session.scalar(
                select(User).where(User.organization_id == organization.id).order_by(User.created_at)
            )
            assert owner is not None
            provider = AIProvider(
                organization_id=organization.id,
                name=f"Durable OpenAI {suffix}",
                type="openai",
                status="configured",
                encrypted_api_key=ai_runtime_service.encrypt_provider_secret("test-provider-secret"),
                base_url="https://api.openai.com",
                config={"enabled": True, "cost_per_1k_tokens": 0.1},
            )
            session.add(provider)
            await session.commit()
            await session.refresh(provider)
            provider_id = provider.id

            created = await ai_runtime_service.create_agent(
                session,
                {
                    "name": f"Durable Agent {suffix}",
                    "role": "Engineer",
                    "department": "Engineering",
                    "provider_id": provider.id,
                    "model": "test-model",
                    "system_prompt": "Test safely.",
                    "workspace_id": None,
                },
                organization.id,
                owner.id,
            )
            agent_id = created["id"]
            job = await ai_runtime_service.create_job(
                session,
                agent_id,
                organization.id,
                "verify durable runtime execution",
                owner.id,
            )
            job_id = job.id

        await ai_runtime_service.run_job(job_id)

        async with SessionLocal() as session:
            stored_job = await session.get(Job, job_id)
            stored_agent = await session.get(AIAgent, agent_id)
            stored_provider = await session.get(AIProvider, provider_id)
            assert stored_job is not None and stored_job.status == "completed"
            assert stored_job.result["text"] == "verified provider response"
            assert stored_agent is not None
            assert stored_agent.metrics["tasks_completed"] == 1
            assert stored_agent.metrics["tokens_used"] == 7
            assert stored_provider is not None
            assert stored_provider.config["usage_today"] == 7
            assert stored_provider.status == "connected"
            assert await session.scalar(
                select(AuditEvent).where(
                    AuditEvent.resource_id == job_id,
                    AuditEvent.action == "ai.job.completed",
                )
            ) is not None
            assert await session.scalar(
                select(Notification).where(Notification.source_id == job_id)
            ) is not None
    finally:
        async with SessionLocal() as session:
            if job_id:
                await session.execute(delete(Notification).where(Notification.source_id == job_id))
                await session.execute(delete(AuditEvent).where(AuditEvent.resource_id == job_id))
                await session.execute(delete(Job).where(Job.id == job_id))
            if agent_id:
                await session.execute(delete(AuditEvent).where(AuditEvent.resource_id == agent_id))
                await session.execute(delete(AIAgent).where(AIAgent.id == agent_id))
            if provider_id:
                await session.execute(delete(AuditEvent).where(AuditEvent.resource_id == provider_id))
                await session.execute(delete(AIProvider).where(AIProvider.id == provider_id))
            await session.commit()


@pytest.mark.asyncio
async def test_provider_cannot_be_removed_while_assigned() -> None:
    await seed()
    suffix = uuid4().hex[:12]
    provider_id: str | None = None
    agent_id: str | None = None
    try:
        async with SessionLocal() as session:
            owner = await session.scalar(select(User).where(User.organization_id == "aionex-org").order_by(User.created_at))
            assert owner is not None
            provider = AIProvider(
                organization_id="aionex-org",
                name=f"Assigned {suffix}",
                type="openai",
                status="configured",
                encrypted_api_key=ai_runtime_service.encrypt_provider_secret("test-provider-secret"),
                base_url="https://api.openai.com",
                config={"enabled": True},
            )
            session.add(provider)
            await session.commit()
            await session.refresh(provider)
            provider_id = provider.id
            created = await ai_runtime_service.create_agent(
                session,
                {"name": f"Assigned Agent {suffix}", "role": "Engineer", "department": "AI", "provider_id": provider.id, "model": "test-model"},
                "aionex-org",
                owner.id,
            )
            agent_id = created["id"]
            with pytest.raises(Exception) as exc:
                await ai_runtime_service.delete_provider(session, provider.id, "aionex-org", owner.id)
            assert getattr(exc.value, "status_code", None) == 409
    finally:
        async with SessionLocal() as session:
            if agent_id:
                await session.execute(delete(AuditEvent).where(AuditEvent.resource_id == agent_id))
                await session.execute(delete(AIAgent).where(AIAgent.id == agent_id))
            if provider_id:
                await session.execute(delete(AuditEvent).where(AuditEvent.resource_id == provider_id))
                await session.execute(delete(AIProvider).where(AIProvider.id == provider_id))
            await session.commit()
