"""Fence complete file-bearing ASGI requests, including response and cleanup.

Queue transactions can commit or roll back before their filesystem effects end.
A separate shared Studio maintenance lock therefore spans body parsing, handler,
streamed response and background/rollback cleanup. This is supplemental admission,
not evidence that older workers, crashed processes or remote providers drained.
"""
from __future__ import annotations

import asyncio

from fastapi.routing import APIRoute
from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send

from app.db.base import SessionLocal
from app.services.host_maintenance_admission import HostMaintenanceClosed, HostMaintenanceUnavailable
from app.services.host_maintenance_studio_admission import require_studio_admission

FILE_ENDPOINTS = frozenset({
    "upload_audio_song_artifact", "download_audio_song_artifact", "delete_audio_song_artifact",
    "create_identity_execution", "provider_input", "download_execution",
    "create_three_d_job", "clarify_three_d_job", "cancel_three_d_job",
    "download_local_three_d_artifact", "get_three_d_artifact_links",
})


class MediaFileRoute(APIRoute):
    """Protect the ASGI lifetime rather than only get_route_handler's return.

    Only the explicitly enumerated file-bearing routes of the three media routers
    use this guard. Ordinary status reads, unknown paths and405 remain unchanged.
    A cancelled request that has not acquired admission is cancelled normally.
    After admission, cancellation is deferred until its one existing handler and
    storage threads finish; cancellation never authorizes a second execution or
    releases the fence while a to_thread write/cleanup can still be running.
    """

    async def handle(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (getattr(self.endpoint, "__name__", "") not in FILE_ENDPOINTS
            or (self.methods and scope["method"] not in self.methods)):
            await super().handle(scope, receive, send)
            return
        admitted = False
        parent = super().handle

        async def guarded() -> None:
            nonlocal admitted
            # The route's business session cannot commit or roll back this lock.
            async with SessionLocal() as fence:
                try:
                    await require_studio_admission(fence)
                except (HostMaintenanceClosed, HostMaintenanceUnavailable):
                    await JSONResponse(
                        status_code=503,
                        content={"detail": {"code": "MEDIA_FILE_MAINTENANCE_UNAVAILABLE"}},
                        headers={"Cache-Control": "no-store"},
                    )(scope, receive, send)
                    return
                admitted = True
                await parent(scope, receive, send)
            # Session exit rolls back the lock-only transaction; no policy writes.

        task = asyncio.create_task(guarded(), name="aionex-maintenance-bound-media-http")
        cancellation_requested = False
        acquisition_cancelled = False
        while True:
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                if task.cancelled():
                    raise
                cancellation_requested = True
                if not admitted and not task.done() and not acquisition_cancelled:
                    acquisition_cancelled = True
                    task.cancel()
                if task.done():
                    # Retrieve a concurrent result/exception without leaving a task.
                    try:
                        task.result()
                    except Exception:
                        raise asyncio.CancelledError from None
                    raise
                continue
            except Exception:
                if cancellation_requested:
                    raise asyncio.CancelledError from None
                raise
            if cancellation_requested:
                raise asyncio.CancelledError
            return
