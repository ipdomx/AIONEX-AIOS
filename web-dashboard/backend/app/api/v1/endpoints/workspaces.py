"""Workspaces endpoints."""

from fastapi import APIRouter

router = APIRouter()

@router.get("")
async def list_workspaces():
    """List all workspaces."""
    return {"message": "workspaces endpoint - implement as needed"}
