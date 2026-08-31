"""Durable AI provider management endpoints."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ai_runtime import FINAL_SUPPORTED_PROVIDER_TYPES, provider_models
from app.core.auth import UserRecord, require_permissions
from app.core.owner_policy import require_owner_service_allowed
from app.db.base import get_db
from app.services import ai_runtime_service

router = APIRouter()


class ProviderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    type: str = Field(min_length=1, max_length=64)
    api_key: str = Field(default="", max_length=8192)
    base_url: Optional[str] = Field(default=None, max_length=2048)
    organization_id: Optional[str] = None
    cost_per_1k_tokens: float = Field(default=0.0, ge=0)
    usage_limit: int = Field(default=0, ge=0)


@router.get("")
async def list_providers(
    user: UserRecord = Depends(require_permissions("providers:read")),
    session: AsyncSession = Depends(get_db),
):
    return await ai_runtime_service.list_providers(
        session,
        user.organization_id,
        include_environment=user.role == "Super Owner",
    )


@router.get("/catalog/supported")
async def supported_provider_catalog(
    user: UserRecord = Depends(require_permissions("providers:read")),
    session: AsyncSession = Depends(get_db),
):
    configured = {
        item["type"]: item
        for item in await ai_runtime_service.list_providers(
            session,
            user.organization_id,
            include_environment=user.role == "Super Owner",
        )
    }
    rows = []
    for provider_type in FINAL_SUPPORTED_PROVIDER_TYPES:
        item = configured.get(provider_type)
        contract = ai_runtime_service.provider_runtime_contract(provider_type)
        catalog_only = provider_type in ai_runtime_service.DEDICATED_3D_PROVIDER_TYPES
        rows.append(
            {
                "type": provider_type,
                "configured": False if catalog_only else bool(item and item["configured"]),
                "enabled": False if catalog_only else bool(item and item["enabled"]),
                "status": "catalog-only" if catalog_only else (item["status"] if item else "unconfigured"),
                "runtime_mode": contract["runtime_mode"],
                "protocol": contract["protocol"],
                "reason": contract["reason"],
                "models": provider_models(provider_type),
            }
        )
    return rows


@router.post("", status_code=201)
async def create_provider(
    data: ProviderCreate,
    user: UserRecord = Depends(require_permissions("providers:write")),
    session: AsyncSession = Depends(get_db),
):
    payload = data.model_dump(exclude={"organization_id"})
    return await ai_runtime_service.create_provider(
        session, payload, user.organization_id, user.id
    )


@router.get("/{provider_id}")
async def get_provider(
    provider_id: str,
    user: UserRecord = Depends(require_permissions("providers:read")),
    session: AsyncSession = Depends(get_db),
):
    provider = await ai_runtime_service.get_provider(
        session, provider_id, user.organization_id
    )
    return {
        **ai_runtime_service.provider_snapshot(provider),
        "models": provider_models(provider.type),
    }


@router.delete("/{provider_id}")
async def delete_provider(
    provider_id: str,
    user: UserRecord = Depends(require_permissions("providers:write")),
    session: AsyncSession = Depends(get_db),
):
    await ai_runtime_service.delete_provider(
        session, provider_id, user.organization_id, user.id
    )
    return {"message": "Provider removed successfully"}


@router.post("/{provider_id}/test")
async def test_provider(
    provider_id: str,
    user: UserRecord = Depends(require_permissions("providers:write")),
    session: AsyncSession = Depends(get_db),
):
    provider = await ai_runtime_service.get_provider(
        session, provider_id, user.organization_id, lock=True
    )
    await require_owner_service_allowed(session, provider.type)
    try:
        result = await ai_runtime_service.provider_health_probe(provider)
    except HTTPException:
        config = dict(provider.config or {})
        config["last_health_check"] = ai_runtime_service._now().isoformat()
        config["last_health_status"] = "error"
        provider.config = config
        provider.status = "error"
        await session.commit()
        raise
    config = dict(provider.config or {})
    config["last_health_status"] = str(result.get("status") or "unknown")
    config["latency_ms"] = int(float(result.get("latency_ms", 0) or 0))
    config["last_health_check"] = ai_runtime_service._now().isoformat()
    provider.config = config
    if result["status"] == "success":
        provider.status = "connected"
    elif result["status"] in {"configured", "disabled", "unconfigured"}:
        provider.status = result["status"]
    await session.commit()
    return result
