"""Meetings endpoints."""

from fastapi import APIRouter

router = APIRouter()

@router.get("")
async def list_meetings():
    """List all meetings."""
    return {"message": "meetings endpoint - implement as needed"}
