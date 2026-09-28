"""Real PostgreSQL + ASGI file-request maintenance lifetime acceptance.

All credentials, uploads and disk files are synthetic and exclusively owned by
this laboratory. No provider request, production database or customer input.
"""
from __future__ import annotations

import importlib
import hashlib
import io
import wave
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1.endpoints import audio_song_artifacts, identity_media, three_d_jobs
from app.core.config import settings
from app.db.models import OwnerControlRecord
from app.services.audio_song_artifact_bridge import issue_artifact_token
from app.services import host_maintenance_admission as maintenance
from tests.test_fr06d10a_media_claim_fence import case as case
from tests.test_fr06d10a_media_claim_fence import _open

SECRET = "synthetic-media-http-admission-test-secret-at-least-32-characters"
ARTIFACT = "a" * 48
ENTRIES = (
    ("POST", "/artifacts/" + ARTIFACT, "put"),
    ("GET", "/artifacts/" + ARTIFACT, "get"),
    ("DELETE", "/artifacts/" + ARTIFACT, "delete"),
    ("POST", "/studio/identity-media/executions", None),
    ("GET", "/studio/identity-media/provider-input/invalid-token/input.png", None),
    ("GET", "/studio/identity-media/executions/invalid-id/download", None),
    ("POST", "/projects/synthetic/3d/jobs", None),
    ("POST", "/projects/synthetic/3d/jobs/synthetic/clarify", None),
    ("POST", "/projects/synthetic/3d/jobs/synthetic/cancel", None),
    ("GET", "/projects/3d/artifacts/local?token=" + "a" * 100, None),
    ("GET", "/projects/synthetic/3d/jobs/synthetic/artifact", None),
)


def _module():
    try:
        return importlib.import_module("app.services.host_maintenance_media_http")
    except ModuleNotFoundError as exc:
        if exc.name != "app.services.host_maintenance_media_http":
            raise
        return None  # Baseline must test the unchanged API before the guard exists.


def _app(case, monkeypatch, root):
    module = _module()
    if module is not None:
        monkeypatch.setattr(module, "SessionLocal", case.sessions)
    monkeypatch.setattr(settings, "SECRET_KEY", SECRET)
    monkeypatch.setattr(settings, "AUDIO_SONG_ARTIFACT_BRIDGE_ROOT", str(root))
    monkeypatch.setattr(settings, "AUDIO_SONG_ARTIFACT_RETENTION_SECONDS", 3600)
    app = FastAPI()
    app.include_router(audio_song_artifacts.router, prefix="/artifacts")
    app.include_router(identity_media.router)
    app.include_router(three_d_jobs.router, prefix="/projects")
    return app


async def _set(case, status):
    if status == "closed":
        return
    async with case.sessions() as session, session.begin():
        row = await session.get(OwnerControlRecord, case.authority_id)
        if status == "missing":
            await session.delete(row)
        elif status == "malformed":
            row.payload = {"unexpected": True}
        elif status == "schema6":
            row.status, row.enabled = "open", True
            row.payload = {**row.payload, "schema_version": 6, "scope": maintenance.SCAN_REQUEST_COVERAGE_SCOPE}
        else:
            raise AssertionError(status)
    case.sql.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ENTRIES, ids=[x[0] + x[1].split("?")[0] for x in ENTRIES])
@pytest.mark.parametrize("state", ["closed", "missing", "malformed", "schema6"])
async def test_denied_real_route_precedes_body_parsing_storage_and_auth_database(case, monkeypatch, tmp_path, entry, state):
    await _set(case, state)
    root = tmp_path / "not-created"
    app = _app(case, monkeypatch, root)
    method, path, action = entry
    reads = []
    async def content():
        reads.append(True)
        yield b"synthetic multipart content that must never be parsed"
    headers = {}
    if action:
        credential = issue_artifact_token(action, ARTIFACT, secret=SECRET, ttl_seconds=300)
        headers["Authorization"] = "Bearer " + credential
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.request(method, path, headers=headers,
                                        content=content() if method == "POST" else None)
    assert response.status_code == 503, response.text
    assert not reads, "maintenance denial must precede request-body or multipart reads"
    assert not root.exists(), "even an authenticated GET may purge/create the artifact root"
    assert response.headers["cache-control"] == "no-store"
    assert not any(q.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for q in case.sql)


def _wav():
    output = io.BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setnchannels(2)
        writer.setsampwidth(2)
        writer.setframerate(48000)
        writer.writeframes(b"\x00\x00\x00\x00" * 480)
    return output.getvalue()


@pytest.mark.asyncio
async def test_open_actual_artifact_put_get_delete_preserves_token_hash_and_write_once_contract(case, monkeypatch, tmp_path):
    await _open(case)
    root = tmp_path / "artifacts"
    app = _app(case, monkeypatch, root)
    body = _wav()
    sha = hashlib.sha256(body).hexdigest()
    def headers(action):
        return {"Authorization": "Bearer " + issue_artifact_token(action, ARTIFACT, secret=SECRET, ttl_seconds=300)}
    put = {**headers("put"), "Content-Type": "audio/wav", "X-AIONEX-Artifact-Size": str(len(body)), "X-AIONEX-Artifact-SHA256": sha}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        path = "/artifacts/" + ARTIFACT
        assert (await client.post(path, headers=put, content=body)).status_code == 201
        assert (await client.post(path, headers=put, content=body)).status_code == 409
        response = await client.get(path, headers=headers("get"))
        assert response.status_code == 200 and hashlib.sha256(response.content).hexdigest() == sha
        assert (await client.get(path, headers=headers("put"))).status_code == 404
        assert (await client.delete(path, headers=headers("delete"))).status_code == 204
    assert not list(root.iterdir())


@pytest.mark.asyncio
async def test_unknown_paths_and_methods_keep_original_http_semantics(case, monkeypatch, tmp_path):
    app = _app(case, monkeypatch, tmp_path / "unused")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/unknown-path")).status_code == 404
        assert (await client.put("/artifacts/" + ARTIFACT)).status_code == 405
    assert not case.sql


async def _observed_guard(case, monkeypatch):
    import asyncio
    from sqlalchemy import text
    module = _module()
    assert module is not None
    acquired = asyncio.Event()
    data = {}
    original = module.require_studio_admission
    async def check(session):
        result = await original(session)
        data["pid"] = await session.scalar(text("SELECT pg_backend_pid()"))
        acquired.set()
        return result
    monkeypatch.setattr(module, "SessionLocal", case.sessions)
    monkeypatch.setattr(module, "require_studio_admission", check)
    return module, acquired, data


def _synthetic_app(module, endpoint, methods=None):
    # Only the test route is synthetic. The ASGI framework, request lifetime,
    # PostgreSQL admission/locks, storage operation and response are real.
    endpoint.__name__ = "upload_audio_song_artifact"
    app = FastAPI()
    app.router.route_class = module.MediaFileRoute
    app.add_api_route("/synthetic-file", endpoint, methods=methods or ["GET"])
    return app


def _scope(method="GET"):
    return {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"},
            "http_version": "1.1", "scheme": "http", "method": method,
            "path": "/synthetic-file", "raw_path": b"/synthetic-file", "root_path": "",
            "query_string": b"", "headers": [], "client": ("127.0.0.1", 1234),
            "server": ("test", 80)}


async def _close(case):
    return await maintenance.close_admission(operation_id=case.operation,
        expected_generation=26, reason="Real ASGI file lifecycle serialization",
        session_factory=case.sessions)


@pytest.mark.asyncio
@pytest.mark.parametrize("transaction", ["commit", "rollback"])
async def test_business_transaction_end_does_not_release_request_fence_before_cleanup(case, monkeypatch, tmp_path, transaction):
    import asyncio
    from fastapi.responses import Response
    from tests.test_fr06d10a_media_claim_fence import _wait_for_lock
    await _open(case)
    module, acquired, holder = await _observed_guard(case, monkeypatch)
    cleanup_started, release = asyncio.Event(), asyncio.Event()
    artifact = tmp_path / "cleanup-completed"
    async def endpoint():
        async with case.sessions() as session:
            session.add(OwnerControlRecord(domain="synthetic-http-lifetime", resource_id=uuid4().hex, payload={}))
            await session.flush()
            await getattr(session, transaction)()
        cleanup_started.set()
        await release.wait()
        artifact.write_bytes(b"owned cleanup finished")
        return Response(status_code=204)
    app = _synthetic_app(module, endpoint)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        request = asyncio.create_task(client.get("/synthetic-file"))
        closing = None
        try:
            await asyncio.wait_for(cleanup_started.wait(), 2)
            closing = asyncio.create_task(_close(case))
            await _wait_for_lock(case, holder["pid"])
            assert not closing.done() and acquired.is_set() and not artifact.exists()
            release.set()
            assert (await asyncio.wait_for(request, 3)).status_code == 204
            assert (await asyncio.wait_for(closing, 3)).generation == 27
            assert artifact.read_bytes() == b"owned cleanup finished"
        finally:
            release.set()
            await asyncio.gather(request, *([closing] if closing else []), return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True], ids=["normal", "repeated-cancel"])
async def test_fence_spans_actual_file_response_last_send(case, monkeypatch, tmp_path, cancel):
    import asyncio
    from fastapi.responses import FileResponse
    from tests.test_fr06d10a_media_claim_fence import _wait_for_lock
    await _open(case)
    module, _, holder = await _observed_guard(case, monkeypatch)
    path = tmp_path / "synthetic-download.bin"
    payload = b"owned-file-response" * 10000
    path.write_bytes(payload)
    async def endpoint():
        return FileResponse(path, media_type="application/octet-stream")
    app = _synthetic_app(module, endpoint)
    sending, release = asyncio.Event(), asyncio.Event()
    received = bytearray()
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}
    async def send(message):
        if message["type"] == "http.response.body":
            sending.set()
            await release.wait()
            received.extend(message.get("body", b""))
    request = asyncio.create_task(app(_scope(), receive, send))
    closing = None
    try:
        await asyncio.wait_for(sending.wait(), 3)
        closing = asyncio.create_task(_close(case))
        await _wait_for_lock(case, holder["pid"])
        if cancel:
            request.cancel()
            await asyncio.sleep(.03)
            request.cancel()
            await asyncio.sleep(.03)
            assert not request.done(), "cancel must not detach a started file response"
        assert not closing.done()
        release.set()
        if cancel:
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(request, 3)
        else:
            await asyncio.wait_for(request, 3)
        assert (await asyncio.wait_for(closing, 3)).generation == 27
        assert bytes(received) == payload
    finally:
        release.set()
        await asyncio.gather(request, *([closing] if closing else []), return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("fail", [False, True], ids=["success", "storage-error"])
async def test_repeated_cancellation_waits_for_real_storage_thread_and_background_cleanup(case, monkeypatch, tmp_path, fail):
    import asyncio
    import threading
    from fastapi.responses import Response
    from starlette.background import BackgroundTask
    from tests.test_fr06d10a_media_claim_fence import _wait_for_lock
    await _open(case)
    module, _, holder = await _observed_guard(case, monkeypatch)
    started = asyncio.Event()
    release, finished = threading.Event(), threading.Event()
    loop = asyncio.get_running_loop()
    calls = []
    artifact = tmp_path / "storage-thread-result"
    def storage():
        calls.append(True)
        loop.call_soon_threadsafe(started.set)
        if not release.wait(4):
            raise AssertionError("Test did not release its owned thread")
        try:
            artifact.write_bytes(b"owned thread complete")
            if fail:
                raise RuntimeError("Synthetic storage failure after owned write")
        finally:
            finished.set()
    async def background():
        await asyncio.to_thread(storage)
    async def endpoint():
        return Response(status_code=204, background=BackgroundTask(background))
    app = _synthetic_app(module, endpoint)
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}
    async def send(message):
        pass
    request = asyncio.create_task(app(_scope(), receive, send))
    closing = None
    try:
        await asyncio.wait_for(started.wait(), 2)
        closing = asyncio.create_task(_close(case))
        await _wait_for_lock(case, holder["pid"])
        for _ in range(3):
            request.cancel()
            await asyncio.sleep(.025)
        assert not request.done() and not closing.done() and not finished.is_set()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(request, 3)
        assert finished.is_set() and calls == [True]
        assert artifact.read_bytes() == b"owned thread complete"
        assert (await asyncio.wait_for(closing, 3)).generation == 27
        assert not [t for t in asyncio.all_tasks() if t.get_name() == "aionex-maintenance-bound-media-http" and not t.done()]
    finally:
        release.set()
        await asyncio.gather(request, *([closing] if closing else []), return_exceptions=True)


@pytest.mark.asyncio
async def test_cancel_while_waiting_for_admission_never_starts_body_or_effect(case, monkeypatch):
    import asyncio
    from fastapi.responses import Response
    from sqlalchemy import text
    from tests.test_fr06d10a_media_claim_fence import _wait_for_lock
    await _open(case)
    module, acquired, _ = await _observed_guard(case, monkeypatch)
    effects = []
    async def endpoint():
        effects.append(True)
        return Response(status_code=204)
    app = _synthetic_app(module, endpoint)
    async def receive():
        raise AssertionError("Request body must not be read before admission")
    async def send(message):
        effects.append(message)
    async with case.sessions() as holder:
        await maintenance._locked_snapshot(holder, exclusive=True)
        pid = await holder.scalar(text("SELECT pg_backend_pid()"))
        request = asyncio.create_task(app(_scope(), receive, send))
        try:
            await _wait_for_lock(case, pid)
            request.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(request, 3)
            assert not effects and not acquired.is_set()
        finally:
            await holder.rollback()
            if not request.done():
                request.cancel()
            await asyncio.gather(request, return_exceptions=True)
    assert not effects


@pytest.mark.asyncio
async def test_actual_upload_holds_fence_across_request_body_and_write_publication(case, monkeypatch, tmp_path):
    import asyncio
    from tests.test_fr06d10a_media_claim_fence import _wait_for_lock
    await _open(case)
    root = tmp_path / "artifacts"
    app = _app(case, monkeypatch, root)
    _, _, holder = await _observed_guard(case, monkeypatch)
    streaming, release = asyncio.Event(), asyncio.Event()
    body = _wav()
    async def content():
        yield body[:44]
        streaming.set()
        await release.wait()
        yield body[44:]
    headers = {"Authorization": "Bearer " + issue_artifact_token("put", ARTIFACT, secret=SECRET, ttl_seconds=300),
               "Content-Type": "audio/wav", "Content-Length": str(len(body)),
               "X-AIONEX-Artifact-Size": str(len(body)), "X-AIONEX-Artifact-SHA256": hashlib.sha256(body).hexdigest()}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        request = asyncio.create_task(client.post("/artifacts/" + ARTIFACT, content=content(), headers=headers))
        closing = None
        try:
            await asyncio.wait_for(streaming.wait(), 3)
            closing = asyncio.create_task(_close(case))
            await _wait_for_lock(case, holder["pid"])
            assert not closing.done()
            release.set()
            assert (await asyncio.wait_for(request, 3)).status_code == 201
            assert (await asyncio.wait_for(closing, 3)).generation == 27
            assert not list(root.glob(".*.tmp"))
            from app.services.audio_song_artifact_bridge import artifact_path
            assert artifact_path(root, ARTIFACT, secret=SECRET).read_bytes() == body
        finally:
            release.set()
            await asyncio.gather(request, *([closing] if closing else []), return_exceptions=True)


@pytest.mark.asyncio
async def test_application_programming_errors_are_not_reclassified_as_maintenance_success(case, monkeypatch):
    await _open(case)
    module, _, _ = await _observed_guard(case, monkeypatch)
    async def endpoint():
        raise ValueError("Synthetic programming error")
    app = _synthetic_app(module, endpoint)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with pytest.raises(ValueError, match="Synthetic programming error"):
            await client.get("/synthetic-file")
    assert (await _close(case)).generation == 27


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["GET", "POST", "DELETE"])
async def test_closed_artifact_request_cannot_purge_an_existing_stale_file(case, monkeypatch, tmp_path, method):
    import os
    import time
    root = tmp_path / "artifacts"
    root.mkdir()
    from app.services.audio_song_artifact_bridge import artifact_path
    victim = artifact_path(root, ARTIFACT, secret=SECRET)
    victim.write_bytes(_wav())
    prior = victim.read_bytes()
    old = time.time() - 7200
    os.utime(victim, (old, old))
    app = _app(case, monkeypatch, root)
    action = {"GET": "get", "POST": "put", "DELETE": "delete"}[method]
    headers = {"Authorization": "Bearer " + issue_artifact_token(action, ARTIFACT, secret=SECRET, ttl_seconds=300)}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.request(method, "/artifacts/" + ARTIFACT, headers=headers)).status_code == 503
    assert victim.read_bytes() == prior and victim.stat().st_mtime == old


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/studio/identity-media/executions", "/projects/synthetic/3d/jobs", "/projects/synthetic/3d/jobs/synthetic/clarify"])
async def test_closed_multipart_request_never_reads_or_spools_upload(case, monkeypatch, tmp_path, path):
    app = _app(case, monkeypatch, tmp_path / "unused")
    called = []
    async def multipart():
        called.append(True)
        yield (b"--synthetic\r\nContent-Disposition: form-data; name=\"image\"; filename=\"synthetic.png\"\r\nContent-Type: image/png\r\n\r\n"
               + b"x" * (2 * 1024 * 1024) + b"\r\n--synthetic--\r\n")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(path, content=multipart(), headers={"Content-Type": "multipart/form-data; boundary=synthetic"})
    assert response.status_code == 503 and not called


@pytest.mark.asyncio
async def test_status_only_routes_are_not_accidentally_turned_into_file_transactions(case, monkeypatch, tmp_path):
    app = _app(case, monkeypatch, tmp_path / "unused")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/studio/identity-media/capabilities")
    assert response.status_code == 401  # Normal authentication, not file503.
    assert not case.sql








def test_file_fence_uses_a_separate_engine_from_business_session_pool():
    from app.db.base import SessionLocal as business_sessions
    module = _module()
    assert module is not None
    assert module.SessionLocal.kw["bind"] is not business_sessions.kw["bind"], (
        "File fences must not exhaust the business pool while handlers wait for a second connection"
    )
