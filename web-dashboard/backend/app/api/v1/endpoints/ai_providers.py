"""AI Providers endpoints."""

from fastapi import APIRouter, Query
from pydantic import BaseModel
from typing import List, Optional

router = APIRouter()

class ProviderCreate(BaseModel):
    name: str
    type: str
    api_key: str
    base_url: Optional[str] = None
    organization_id: str

class ProviderResponse(BaseModel):
    id: str
    name: str
    type: str
    status: str
    latency: int
    cost_per_1k_tokens: float
    usage_today: int
    usage_limit: int
    last_used: Optional[str]
    created_at: str


@router.get("", response_model=List[ProviderResponse])
async def list_providers():
    """List all AI providers."""
    return [
        {
            "id": "provider-1",
            "name": "OpenAI",
            "type": "openai",
            "status": "connected",
            "latency": 145,
            "cost_per_1k_tokens": 0.03,
            "usage_today": 2847291,
            "usage_limit": 10000000,
            "last_used": "2024-01-15T10:00:00Z",
            "created_at": "2024-01-01T00:00:00Z",
        },
        {
            "id": "provider-2",
            "name": "Anthropic",
            "type": "anthropic",
            "status": "connected",
            "latency": 189,
            "cost_per_1k_tokens": 0.008,
            "usage_today": 1245000,
            "usage_limit": 5000000,
            "last_used": "2024-01-15T09:30:00Z",
            "created_at": "2024-01-01T00:00:00Z",
        },
        {
            "id": "provider-3",
            "name": "Google Gemini",
            "type": "google",
            "status": "connected",
            "latency": 234,
            "cost_per_1k_tokens": 0.001,
            "usage_today": 890000,
            "usage_limit": 5000000,
            "last_used": "2024-01-15T08:00:00Z",
            "created_at": "2024-01-01T00:00:00Z",
        },
    ]

@router.post("", status_code=201)
async def create_provider(data: ProviderCreate):
    """Add new AI provider."""
    return {"id": "new-provider-id", "message": "Provider added successfully"}

@router.get("/{provider_id}")
async def get_provider(provider_id: str):
    """Get provider by ID."""
    return {
        "id": provider_id,
        "name": "OpenAI",
        "type": "openai",
        "status": "connected",
        "models": [
            {"id": "gpt-4", "name": "GPT-4", "context_window": 8192, "cost_input": 0.03, "cost_output": 0.06},
            {"id": "gpt-4-turbo", "name": "GPT-4 Turbo", "context_window": 128000, "cost_input": 0.01, "cost_output": 0.03},
        ],
    }

@router.delete("/{provider_id}")
async def delete_provider(provider_id: str):
    """Remove provider."""
    return {"message": "Provider removed successfully"}

@router.post("/{provider_id}/test")
async def test_provider(provider_id: str):
    """Test provider connection."""
    return {"status": "success", "latency_ms": 145, "message": "Connection successful"}
