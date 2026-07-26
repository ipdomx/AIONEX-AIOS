"""Notifications endpoints."""

from fastapi import APIRouter

router = APIRouter()

@router.get("")
async def list_notifications():
    """List all notifications."""
    return {"message": "notifications endpoint - implement as needed"}
