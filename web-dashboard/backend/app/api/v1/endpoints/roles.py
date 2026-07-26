"""Roles endpoints."""

from fastapi import APIRouter

router = APIRouter()

@router.get("")
async def list_roles():
    """List all roles."""
    return {"message": "roles endpoint - implement as needed"}
