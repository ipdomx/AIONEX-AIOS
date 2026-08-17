"""Phase 36C launch-model refresh and revocation contracts."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4
from urllib.parse import urlsplit

import pytest
from fastapi import HTTPException
from sqlalchemy import delete

from app.core.config import settings
from app.db.base import SessionLocal
from app.db.models import AIProvider, Organization
from app.services.ai_runtime_service import encrypt_provider_secret
from app.services import project_ai_model_refresh as refresh


def _validated(model: str) -> dict[str, object]:
    now = datetime.now(UTC)
    return {
        "model": model,
        "tasks": ["reasoning"],
        "evidence_ref": f"old:{model}",
        "policy_ref": "old-policy",
        "validated_at": (now - timedelta(minutes=5)).isoformat(),
        "expires_at": (now + timedelta(hours=1)).isoformat(),
        "languages": ["multilingual"],
        "local": False,
        "max_context_tokens": 8192,
        "quality_score": 0.5,
        "latency_score": 0.5,
        "privacy_score": 0.5,
        "input_cost_per_million": 1.0,
        "output_cost_per_million": 1.0,
        "requests_per_minute": 10,
        "concurrent_requests": 1,
        "circuit_failure_threshold": 3,
        "circuit_failure_window_seconds": 60,
        "circuit_open_seconds": 30,
        "lease_seconds": 60,
    }


async def _seed_platform(monkeypatch, *, existing_mistral: bool = False) -> tuple[str, dict[str, str]]:
    suffix = uuid4().hex[:8]
    org_id = f"refresh-org-{suffix}"
    monkeypatch.setattr(settings, "PROJECT_AI_PLATFORM_PROVIDER_ORGANIZATION_ID", org_id)
    ids = {name: f"refresh-{name}-{suffix}" for name in ("openai", "ollama", "mistral", "deepseek")}
    async with SessionLocal() as session:
        session.add(Organization(id=org_id, name="Refresh Platform", slug=org_id, plan="enterprise", status="active"))
        await session.flush()
        session.add_all([
            AIProvider(
                id=ids["openai"], organization_id=org_id, name="OpenAI", type="openai", status="connected",
                encrypted_api_key=encrypt_provider_secret("fake-openai"), base_url="https://api.openai.com", config={"enabled": True},
            ),
            AIProvider(
                id=ids["ollama"], organization_id=org_id, name="Ollama", type="ollama", status="connected",
                base_url="http://ollama:11434", config={"enabled": True},
            ),
            AIProvider(
                id=ids["mistral"], organization_id=org_id, name="Mistral", type="mistral", status="connected",
                encrypted_api_key=encrypt_provider_secret("fake-mistral"), base_url="https://api.mistral.ai",
                config={"enabled": True, **({"validated_models": [_validated("mistral-medium-3-5")]} if existing_mistral else {})},
            ),
            AIProvider(
                id=ids["deepseek"], organization_id=org_id, name="DeepSeek", type="deepseek", status="connected",
                encrypted_api_key=encrypt_provider_secret("fake-deepseek"), base_url="https://api.deepseek.com", config={"enabled": True},
            ),
        ])
        await session.commit()
    return org_id, ids


async def _cleanup(org_id: str) -> None:
    async with SessionLocal() as session:
        await session.execute(delete(Organization).where(Organization.id == org_id))
        await session.commit()


def _inventory_payload(url: str):
    parsed = urlsplit(url)
    hostname = (parsed.hostname or "").lower()
    if hostname == "api.openai.com":
        return {"data": [{"id": "gpt-5.6-sol"}, {"id": "gpt-5.6-terra"}, {"id": "gpt-5.6-luna"}]}
    if hostname == "api.mistral.ai":
        return {"data": [{"id": "mistral-medium-3-5"}]}
    if hostname == "api.deepseek.com":
        return {"data": [{"id": "deepseek-v4-pro"}]}
    if parsed.path.rstrip("/") == "/api/tags":
        return {"models": [{"name": "gemma3:4b"}]}
    raise AssertionError(url)


@pytest.mark.asyncio
async def test_refresh_persists_only_reviewed_current_launch_models(monkeypatch) -> None:
    org_id, ids = await _seed_platform(monkeypatch)

    async def requester(_method, url, **_kwargs):
        return _inventory_payload(url), 2.0

    try:
        async with SessionLocal() as session:
            result = await refresh.refresh_launch_model_evidence(session, requester=requester)
            await session.commit()
        assert set(result["validated"]) == {
            "ollama:gemma3:4b",
            "openai:gpt-5.6-sol",
            "openai:gpt-5.6-terra",
            "openai:gpt-5.6-luna",
            "mistral:mistral-medium-3-5",
            "deepseek:deepseek-v4-pro",
        }
        assert result["unavailable"] == []
        assert result["probe_failures"] == []
        assert result["ttl_seconds"] == 6 * 60 * 60
        async with SessionLocal() as session:
            for provider_type, provider_id in ids.items():
                provider = await session.get(AIProvider, provider_id)
                assert provider is not None
                rows = (provider.config or {}).get("validated_models") or []
                expected = 3 if provider_type == "openai" else 1
                assert len(rows) == expected
                assert all("credential" not in str(row).lower() for row in rows)
    finally:
        await _cleanup(org_id)


@pytest.mark.asyncio
async def test_successful_inventory_revokes_launch_model_that_disappeared(monkeypatch) -> None:
    org_id, ids = await _seed_platform(monkeypatch, existing_mistral=True)

    async def requester(_method, url, **_kwargs):
        payload = _inventory_payload(url)
        if "mistral.ai" in url:
            payload = {"data": [{"id": "other-mistral"}]}
        return payload, 2.0

    async def no_notify(*_args, **_kwargs):
        return []

    monkeypatch.setattr(refresh, "_notify_missing_model", no_notify)
    try:
        async with SessionLocal() as session:
            result = await refresh.refresh_launch_model_evidence(session, requester=requester)
            await session.commit()
        assert "mistral:mistral-medium-3-5" in result["unavailable"]
        assert "mistral:mistral-medium-3-5" in result["revoked"]
        async with SessionLocal() as session:
            provider = await session.get(AIProvider, ids["mistral"])
            assert provider is not None
            rows = (provider.config or {}).get("validated_models") or []
            assert not any(row.get("model") == "mistral-medium-3-5" for row in rows)
    finally:
        await _cleanup(org_id)


@pytest.mark.asyncio
async def test_transient_probe_failure_preserves_existing_evidence(monkeypatch) -> None:
    org_id, ids = await _seed_platform(monkeypatch, existing_mistral=True)

    async def requester(_method, url, **_kwargs):
        if "mistral.ai" in url:
            raise HTTPException(status_code=503, detail="temporary")
        return _inventory_payload(url), 2.0

    try:
        async with SessionLocal() as session:
            result = await refresh.refresh_launch_model_evidence(session, requester=requester)
            await session.commit()
        assert "mistral:probe-failed" in result["probe_failures"]
        async with SessionLocal() as session:
            provider = await session.get(AIProvider, ids["mistral"])
            assert provider is not None
            rows = (provider.config or {}).get("validated_models") or []
            assert any(row.get("model") == "mistral-medium-3-5" for row in rows)
    finally:
        await _cleanup(org_id)
