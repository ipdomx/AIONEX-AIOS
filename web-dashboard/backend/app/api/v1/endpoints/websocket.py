"""Authenticated, continuously revocable websocket delivery for runtime events."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.auth import auth_service
from app.core.logging import get_logger
from app.db.base import SessionLocal
from app.realtime.authorized_socket import (
    AuthorizedRealtimeSocket,
    IDLE_REVALIDATION_SECONDS,
    MAX_CONTROL_MESSAGE_CHARACTERS,
    StreamAuthorizationLost,
)
from app.realtime.runtime import realtime_event_runtime

router = APIRouter()
logger = get_logger(__name__)


@router.get("/status")
async def websocket_status():
    return {"connected_clients": realtime_event_runtime.connected_count()}


@router.websocket("/connect")
async def websocket_connect(websocket: WebSocket, token: str):
    # The raw socket is never enrolled: hub delivery always traverses fresh auth.
    guarded = AuthorizedRealtimeSocket(websocket, token, SessionLocal, authentication=auth_service)
    organization_id: str | None = None
    try:
        principal = await guarded.ensure_authorized()
        organization_id = principal.organization_id
        await realtime_event_runtime.connect(organization_id, guarded)
        await guarded.send_json({"type": "connected", "organization_id": organization_id,
                                 "user_id": principal.user_id})
        while not guarded.closed:
            try:
                message = await asyncio.wait_for(websocket.receive_text(),
                                                 timeout=IDLE_REVALIDATION_SECONDS)
            except TimeoutError:
                await guarded.ensure_authorized()
                continue
            if len(message) > MAX_CONTROL_MESSAGE_CHARACTERS:
                await guarded.close(1009)
                return
            if message == "ping":
                await guarded.send_json({"type": "pong"})
            else:
                await guarded.ensure_authorized()
    except (WebSocketDisconnect, StreamAuthorizationLost):
        return
    except Exception:
        # Auth/transport failures must not echo tokens, URL queries or user data.
        await guarded.close(1013)
    finally:
        if organization_id is not None:
            try:
                async with asyncio.timeout(3.0):
                    await realtime_event_runtime.disconnect(organization_id, guarded)
            except Exception:
                logger.warning("Realtime subscription cleanup unavailable; closing socket")
        await guarded.close()
