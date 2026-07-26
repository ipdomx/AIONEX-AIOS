"""Permissions endpoints."""

from fastapi import APIRouter

router = APIRouter()

@router.get("")
async def list_permissions():
    """List all permissions."""
    return {"message": "permissions endpoint - implement as needed"}
