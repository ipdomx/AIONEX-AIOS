"""Websocket endpoints."""

from fastapi import APIRouter

router = APIRouter()

@router.get("")
async def list_websocket():
    """List all websocket."""
    return {"message": "websocket endpoint - implement as needed"}
