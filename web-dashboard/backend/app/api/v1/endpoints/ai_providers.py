"""AI provider management endpoints."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional

from app.core.ai_runtime import FINAL_SUPPORTED_PROVIDER_TYPES, ai_runtime, provider_models
from app.core.auth import UserRecord, current_user
from app.core.owner_policy import require_owner_service_allowed
from app.db.base import get_db
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


class ProviderCreate(BaseModel):
    name: str
    type: str
    api_key: str
    base_url: Optional[str] = None
    organization_id: Optional[str] = None
    cost_per_1k_tokens: float = 0.0
    usage_limit: int = 0


@router.get("")
async def list_providers(user: UserRecord = Depends(current_user)):
    return ai_runtime.list_providers(user.organization_id)




@router.get("/catalog/supported")
async def supported_provider_catalog(user: UserRecord = Depends(current_user)):
    configured = {item["type"]: item for item in ai_runtime.list_providers(user.organization_id)}
    rows = []
    for provider_type in FINAL_SUPPORTED_PROVIDER_TYPES:
        item = configured.get(provider_type)
        rows.append({
            "type": provider_type,
            "configured": item is not None and item.get("api_key_hint") not in {None, "not-configured"},
            "enabled": bool(item and item.get("enabled")),
            "status": item.get("status", "unconfigured") if item else "unconfigured",
            "models": provider_models(provider_type),
        })
    return rows


@router.post("", status_code=201)
async def create_provider(
    data: ProviderCreate, user: UserRecord = Depends(current_user)
):
    payload = data.model_dump(exclude={"organization_id"})
    return ai_runtime.create_provider(payload, user.organization_id)


@router.get("/{provider_id}")
async def get_provider(provider_id: str, user: UserRecord = Depends(current_user)):
    provider = ai_runtime.get_provider(provider_id, user.organization_id)
    return {
        **provider.__dict__,
        "models": provider_models(provider.type),
    }


@router.delete("/{provider_id}")
async def delete_provider(provider_id: str, user: UserRecord = Depends(current_user)):
    ai_runtime.delete_provider(provider_id, user.organization_id)
    return {"message": "Provider removed successfully"}


@router.post("/{provider_id}/test")
async def test_provider(
    provider_id: str,
    user: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    provider = ai_runtime.get_provider(provider_id, user.organization_id)
    await require_owner_service_allowed(session, provider.type)
    return {
        "status": "success" if provider.enabled else "disabled",
        "latency_ms": provider.latency,
        "message": (
            "Provider configuration is available"
            if provider.enabled
            else "Provider is disabled"
        ),
    }
