"""FR09 middleware regression: pure ASGI path preserves production boundaries."""
from __future__ import annotations

import httpx
import pytest

from main import ProductionSecurityASGIMiddleware


def responder(*, status: int = 200, cache: bytes = b"public, max-age=60"):
    async def response(scope, receive, send):
        if scope["type"] != "http":
            return
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"cache-control", cache),
                (b"server", b"sensitive-backend"),
            ],
        })
        await send({
            "type": "http.response.body",
            "body": b'{"ok":true}',
            "more_body": False,
        })

    return response


async def get(path, *, handler=None, headers=None):
    middleware = ProductionSecurityASGIMiddleware(handler or responder())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=middleware),
        base_url="http://backend",
    ) as client:
        return await client.get(path, headers=headers)


@pytest.mark.asyncio
async def test_production_rejects_untrusted_host_before_downstream(monkeypatch):
    monkeypatch.setattr("main._production", lambda: True)
    monkeypatch.setattr("main._allowed_hosts", lambda: {"trusted.example"})
    async def uncalled(scope, receive, send):
        raise AssertionError("Denied request must not call downstream")
    denied = await get("/api/v1/auth/me", handler=uncalled)
    assert denied.status_code == 421
    assert denied.json()["detail"] == "Untrusted host"
    monkeypatch.setattr("main._allowed_hosts", lambda: set())
    missing = await get("/api/v1/auth/me", handler=uncalled)
    assert missing.status_code == 503
    assert "Production host policy" in missing.text


@pytest.mark.asyncio
async def test_private_api_no_store_and_all_security_headers(monkeypatch):
    monkeypatch.setattr("main._production", lambda: False)
    res = await get("/api/v1/projects", headers={"X-Request-ID": "fr09-probe-unique"})
    assert res.status_code == 200
    assert res.headers["cache-control"] == "no-store"
    assert res.headers["x-request-id"] == "fr09-probe-unique"
    assert res.headers["x-content-type-options"] == "nosniff"
    assert res.headers["x-frame-options"] == "DENY"
    assert res.headers["referrer-policy"] == "no-referrer"
    assert "microphone=(self)" in res.headers["permissions-policy"]
    assert "server" not in res.headers


@pytest.mark.asyncio
async def test_only_explicit_public_portal_cache_preserved(monkeypatch):
    monkeypatch.setattr("main._production", lambda: False)
    for path in ("/api/v1/portal/published", "/api/v1/portal/assets/" + "a" * 32):
        res = await get(path)
        assert res.headers["cache-control"] == "public, max-age=60"
    for path in ("/api/v1/portal/assets/not-a-hash", "/api/v1/projects"):
        res = await get(path)
        assert res.headers["cache-control"] == "no-store"
    res = await get("/api/v1/portal/published", handler=responder(status=500))
    assert res.headers["cache-control"] == "no-store"
    res = await get("/api/v1/portal/published", handler=responder(status=304))
    assert res.headers["cache-control"] == "public, max-age=60"


@pytest.mark.asyncio
async def test_non_http_scope_is_forwarded_without_modification(monkeypatch):
    monkeypatch.setattr("main._production", lambda: True)
    seen = []
    async def passthrough(scope, receive, send):
        seen.append(scope)
    wrapped = ProductionSecurityASGIMiddleware(passthrough)
    ws = {"type": "websocket", "path": "/ws/probe"}
    async def ignored(_):
        return {}
    await wrapped(ws, ignored, ignored)
    assert seen == [ws]


@pytest.mark.asyncio
async def test_streaming_body_chunks_are_not_buffered(monkeypatch):
    monkeypatch.setattr("main._production", lambda: False)
    chunks = []
    async def stream(scope, receive, send):
        await send({"type":"http.response.start", "status":200, "headers":[]})
        await send({"type":"http.response.body", "body":b"first", "more_body":True})
        await send({"type":"http.response.body", "body":b"second", "more_body":False})
    wrapped = ProductionSecurityASGIMiddleware(stream)
    async def receive():
        return {"type":"http.request", "body":b"", "more_body":False}
    async def send(data):
        chunks.append(data)
    await wrapped({"type":"http", "method":"GET", "path":"/api/v1/projects",
                   "headers":[(b"host",b"backend")]}, receive, send)
    assert [x["type"] for x in chunks] == [
        "http.response.start", "http.response.body", "http.response.body"
    ]
    assert [x["body"] for x in chunks[1:]] == [b"first",b"second"]
