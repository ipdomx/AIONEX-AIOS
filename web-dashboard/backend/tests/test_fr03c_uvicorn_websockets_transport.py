from __future__ import annotations

import asyncio
import json
import socket
from importlib.metadata import version
from types import SimpleNamespace

import pytest
import uvicorn
import websockets
from fastapi import FastAPI

from app.api.v1.endpoints import websocket as websocket_endpoint


class _DummySession:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _DummyAuthService:
    async def decode_access_token(self, token: str) -> dict[str, object]:
        assert token == "transport-test"
        return {"sub": "user-1", "auth_version": 7}

    async def get_user_by_id(self, _session: object, user_id: str):
        assert user_id == "user-1"
        return SimpleNamespace(
            id="user-1",
            organization_id="tenant-1",
            auth_version=7,
            role="member",
        )


class _DummyRealtimeRuntime:
    def __init__(self) -> None:
        self.connected = 0

    async def connect(self, tenant_id: str, websocket: object) -> None:
        assert tenant_id == "tenant-1"
        await websocket.accept()  # type: ignore[attr-defined]
        self.connected += 1

    async def disconnect(self, tenant_id: str, _websocket: object) -> None:
        assert tenant_id == "tenant-1"
        self.connected -= 1

    def connected_count(self, _tenant_id: str | None = None) -> int:
        return self.connected


@pytest.mark.asyncio
async def test_uvicorn_websockets_transport_uses_project_realtime_endpoint(monkeypatch) -> None:
    assert version("uvicorn") == "0.52.4"
    assert version("websockets") == "17.1"

    runtime = _DummyRealtimeRuntime()
    monkeypatch.setattr(websocket_endpoint, "auth_service", _DummyAuthService())
    monkeypatch.setattr(websocket_endpoint, "SessionLocal", _DummySession)
    monkeypatch.setattr(websocket_endpoint, "realtime_event_runtime", runtime)

    app = FastAPI()
    app.include_router(websocket_endpoint.router, prefix="/realtime")

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    listener.setblocking(False)
    port = listener.getsockname()[1]

    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="error",
        lifespan="off",
        ws="auto",
    )
    config.load()
    assert config.ws_protocol_class is not None
    assert config.ws_protocol_class.__module__.endswith("websockets_sansio_impl")
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None  # type: ignore[method-assign]
    server_task = asyncio.create_task(server.serve(sockets=[listener]))

    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(0.01)
        assert server.started

        async with websockets.connect(
            f"ws://127.0.0.1:{port}/realtime/connect?token=transport-test",
            open_timeout=5,
            close_timeout=5,
        ) as client:
            connected = json.loads(await asyncio.wait_for(client.recv(), timeout=5))
            assert connected == {
                "type": "connected",
                "organization_id": "tenant-1",
                "user_id": "user-1",
            }
            assert runtime.connected == 1

            await client.send("ping")
            pong = json.loads(await asyncio.wait_for(client.recv(), timeout=5))
            assert pong == {"type": "pong"}

        for _ in range(100):
            if runtime.connected == 0:
                break
            await asyncio.sleep(0.01)
        assert runtime.connected == 0
    finally:
        server.should_exit = True
        await asyncio.wait_for(server_task, timeout=10)
        listener.close()
