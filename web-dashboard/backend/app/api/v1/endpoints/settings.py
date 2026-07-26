"""Settings endpoints."""

from fastapi import APIRouter

router = APIRouter()

@router.get("")
async def list_settings():
    """List all settings."""
    return {"message": "settings endpoint - implement as needed"}
