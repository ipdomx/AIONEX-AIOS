"""Authenticated websocket delivery for AIOS runtime events."""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.ai_runtime import ai_runtime
from app.core.auth import auth_service
from app.db.base import SessionLocal

router = APIRouter()


@router.get("/status")
async def websocket_status():
    return {"connected_clients": ai_runtime.hub.connected_count()}


@router.websocket("/connect")
async def websocket_connect(websocket: WebSocket, token: str):
    try:
        payload = await auth_service.decode_access_token(token)
        async with SessionLocal() as session:
            user = await auth_service.get_user_by_id(session, str(payload["sub"]))
        if int(payload.get("auth_version", 0)) != user.auth_version:
            raise PermissionError("Access token generation is no longer valid")
    except Exception:
        await websocket.close(code=4401)
        return

    organization_id = user.organization_id
    await ai_runtime.hub.connect(organization_id, websocket)
    await websocket.send_json(
        {
            "type": "connected",
            "organization_id": organization_id,
            "user_id": user.id,
        }
    )
    try:
        while True:
            message = await websocket.receive_text()
            if message == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        await ai_runtime.hub.disconnect(organization_id, websocket)
