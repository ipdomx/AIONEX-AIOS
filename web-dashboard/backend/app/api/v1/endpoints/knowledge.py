"""Knowledge endpoints."""

from fastapi import APIRouter

router = APIRouter()

@router.get("")
async def list_knowledge():
    """List all knowledge."""
    return {"message": "knowledge endpoint - implement as needed"}
