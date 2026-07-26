"""Organizations endpoints."""

from fastapi import APIRouter

router = APIRouter()

@router.get("")
async def list_organizations():
    """List all organizations."""
    return {"message": "organizations endpoint - implement as needed"}
