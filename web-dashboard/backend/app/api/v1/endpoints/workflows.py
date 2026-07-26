"""Workflows endpoints."""

from fastapi import APIRouter

router = APIRouter()

@router.get("")
async def list_workflows():
    """List all workflows."""
    return {"message": "workflows endpoint - implement as needed"}
