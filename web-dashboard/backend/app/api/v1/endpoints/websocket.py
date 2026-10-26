"""Authenticated, continuously revocable websocket delivery for runtime events."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.auth import auth_service
from app.core.logging import get_logger
from app.db.base import SessionLocal
from app.realtime.fr09_authenticated_presence import ServerPresenceRecorder
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
async def websocket_connect(
    websocket: WebSocket,
    token: str,
    after_event_id: str = "",
):
    # The raw socket is never enrolled: hub delivery always traverses fresh auth.
    guarded = AuthorizedRealtimeSocket(websocket, token, SessionLocal, authentication=auth_service)
    organization_id: str | None = None
    presence: ServerPresenceRecorder | None = None
    presence_socket_id: str | None = None
    presence_user_digest: str | None = None
    try:
        principal = await guarded.ensure_authorized()
        # Optional FR09 metering is bound to a backend-authenticated socket.
        # No client-supplied counts, identities or samples are ever accepted.
        presence = await ServerPresenceRecorder.from_enabled_config()
        organization_id = principal.organization_id
        resume_cursor = after_event_id.strip() or None
        if resume_cursor is not None and len(resume_cursor) > 256:
            await guarded.close(1008)
            return
        if resume_cursor is None:
            await realtime_event_runtime.connect(organization_id, guarded)
        else:
            await realtime_event_runtime.connect(
                organization_id, guarded, after_event_id=resume_cursor
            )
        if presence is not None:
            presence_socket_id, presence_user_digest = await presence.register(
                principal
            )
        await guarded.send_json({"type": "connected", "organization_id": organization_id,
                                 "user_id": principal.user_id})
        if resume_cursor is not None:
            await realtime_event_runtime.replay(
                organization_id, guarded, after_event_id=resume_cursor
            )
        while not guarded.closed:
            try:
                message = await asyncio.wait_for(websocket.receive_text(),
                                                 timeout=IDLE_REVALIDATION_SECONDS)
            except TimeoutError:
                principal = await guarded.ensure_authorized()
                if presence is not None and presence_socket_id is not None:
                    await presence.revalidate(
                        presence_socket_id, presence_user_digest or "", principal
                    )
                continue
            if len(message) > MAX_CONTROL_MESSAGE_CHARACTERS:
                await guarded.close(1009)
                return
            if message == "ping":
                await guarded.send_json({"type": "pong"})
                principal = guarded.principal
            else:
                principal = await guarded.ensure_authorized()
            if presence is not None and presence_socket_id is not None:
                await presence.revalidate(
                    presence_socket_id, presence_user_digest or "", principal
                )
    except (WebSocketDisconnect, StreamAuthorizationLost):
        return
    except Exception:
        # Auth/transport failures must not echo tokens, URL queries or user data.
        await guarded.close(1013)
    finally:
        if presence is not None and presence_socket_id is not None:
            try:
                async with asyncio.timeout(3.0):
                    await presence.disconnect(presence_socket_id)
            except Exception:
                # Redis TTL enforces eventual removal on unexpected disconnect.
                logger.warning("FR09 socket presence cleanup unavailable")
        if organization_id is not None:
            try:
                async with asyncio.timeout(3.0):
                    await realtime_event_runtime.disconnect(organization_id, guarded)
            except Exception:
                logger.warning("Realtime subscription cleanup unavailable; closing socket")
        await guarded.close()
