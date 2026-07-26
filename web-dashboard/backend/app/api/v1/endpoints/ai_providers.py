"""AI provider management endpoints."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional

from app.core.ai_runtime import ai_runtime
from app.core.auth import UserRecord, current_user

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


@router.post("", status_code=201)
async def create_provider(data: ProviderCreate, user: UserRecord = Depends(current_user)):
    payload = data.model_dump(exclude={"organization_id"})
    return ai_runtime.create_provider(payload, user.organization_id)


@router.get("/{provider_id}")
async def get_provider(provider_id: str, user: UserRecord = Depends(current_user)):
    provider = ai_runtime.get_provider(provider_id, user.organization_id)
    return {
        **provider.__dict__,
        "models": [],
    }


@router.delete("/{provider_id}")
async def delete_provider(provider_id: str, user: UserRecord = Depends(current_user)):
    ai_runtime.delete_provider(provider_id, user.organization_id)
    return {"message": "Provider removed successfully"}


@router.post("/{provider_id}/test")
async def test_provider(provider_id: str, user: UserRecord = Depends(current_user)):
    provider = ai_runtime.get_provider(provider_id, user.organization_id)
    return {
        "status": "success" if provider.enabled else "disabled",
        "latency_ms": provider.latency,
        "message": "Provider configuration is available" if provider.enabled else "Provider is disabled",
    }
