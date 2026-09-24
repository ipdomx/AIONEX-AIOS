"""Regression for room-scoped LiveKit admin JWTs; no real credentials or I/O."""
from __future__ import annotations

from typing import Any

import httpx
import jwt
import pytest

from app.realtime import livekit_runtime as module


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["list", "remove"])
@pytest.mark.parametrize("room", ["aios-rt-room-a", "aios-rt-room-b"])
async def test_participant_operations_use_only_the_requested_room_admin_grant(
    monkeypatch: pytest.MonkeyPatch, method: str, room: str
) -> None:
    runtime = module.LiveKitRuntime()
    calls: list[dict[str, Any]] = []

    async def transport(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {"participants": []} if method == "list" else {}

    monkeypatch.setattr(runtime, "_twirp", transport)
    if method == "list":
        result = await runtime.list_room_participant_inventory(provider_room_name=room)
        assert result.participant_count == 0
    else:
        await runtime.remove_participant(
            provider_room_name=room, participant_identity="isolated-participant"
        )
    assert len(calls) == 1
    assert calls[0]["service"] == "RoomService"
    assert calls[0]["payload"]["room"] == room
    assert calls[0]["video_grant"] == {"roomAdmin": True, "room": room}


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["list", "remove"])
@pytest.mark.parametrize("room", ["aios-rt-room-a", "aios-rt-room-b"])
async def test_signed_admin_token_keeps_room_binding_through_http_boundary(
    monkeypatch: pytest.MonkeyPatch, method: str, room: str
) -> None:
    runtime = module.LiveKitRuntime()
    # These values are test-only signing fixtures, never provider credentials.
    key = "isolated-livekit-unit-key"
    secret = "isolated-livekit-unit-secret-with-more-than-32-characters"
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(runtime, "_api_credentials", lambda: (key, secret))

    class Transport:
        def __init__(self, **kwargs: Any) -> None:
            assert kwargs["timeout"] == 10.0

        async def __aenter__(self) -> Transport:
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def post(self, url: str, **kwargs: Any) -> httpx.Response:
            token = kwargs["headers"]["Authorization"].removeprefix("Bearer ")
            claims = jwt.decode(token, secret, algorithms=["HS256"])
            captured.append(claims)
            assert url.endswith("/ListParticipants" if method == "list" else "/RemoveParticipant")
            assert kwargs["json"]["room"] == room
            return httpx.Response(200, json={"participants": []} if method == "list" else {})

    monkeypatch.setattr(module.httpx, "AsyncClient", Transport)
    if method == "list":
        await runtime.list_room_participant_inventory(provider_room_name=room)
    else:
        await runtime.remove_participant(
            provider_room_name=room, participant_identity="isolated-participant"
        )
    assert len(captured) == 1
    assert captured[0]["iss"] == key
    assert captured[0]["video"] == {"roomAdmin": True, "room": room}
    assert captured[0]["exp"] > captured[0]["nbf"]
