"""Durable FFmpeg 9 render worker for the Phase 36D media DAG."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import signal
import socket
import time
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.db.base import SessionLocal
from app.db.models import (
    AuditEvent,
    MediaAssetEdge,
    MediaAssetGraph,
    MediaAssetNode,
    MediaRenderStep,
    StudioAsset,
    StudioAssetRevision,
    uuid_str,
)
from app.services.media_ffmpeg import FFmpegRuntime, MediaFFmpegError, MediaRenderResult
from app.services.media_orchestrator import output_profile
from app.services.production_studio import slug
from app.services.media_storage import MediaObjectStore, MediaStorageError, media_object_store
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

logger = get_logger(__name__)
SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class MediaRenderLeaseLost(RuntimeError):
    """The render step lease has been reclaimed or cancelled."""


@dataclass(frozen=True, slots=True)
class RenderClaim:
    step_id: str
    lease_token: str
    fencing_token: int


def _now() -> datetime:
    return datetime.now(UTC)


def _probe_summary(payload: dict[str, Any]) -> dict[str, Any]:
    streams: list[dict[str, Any]] = []
    for raw in payload.get("streams") or []:
        if not isinstance(raw, dict):
            continue
        streams.append(
            {
                key: raw.get(key)
                for key in (
                    "codec_type",
                    "codec_name",
                    "profile",
                    "width",
                    "height",
                    "pix_fmt",
                    "sample_rate",
                    "channels",
                    "duration",
                )
                if raw.get(key) is not None
            }
        )
    raw_format = payload.get("format")
    format_data: dict[str, Any] = raw_format if isinstance(raw_format, dict) else {}
    return {
        "duration": format_data.get("duration"),
        "format_name": format_data.get("format_name"),
        "streams": streams,
    }


class MediaRenderWorker:
    def __init__(
        self,
        *,
        session_factory: SessionFactory = SessionLocal,
        store: MediaObjectStore | None = None,
        runtime: FFmpegRuntime | None = None,
        worker_id: str | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.store = store or media_object_store()
        self.runtime = runtime or FFmpegRuntime()
        configured = (worker_id or settings.MEDIA_RENDER_WORKER_ID).strip()
        self.worker_id = configured or f"media-render:{socket.gethostname()}"
        self.stop_event = asyncio.Event()
        self.health_path = Path(settings.MEDIA_RENDER_WORKER_HEALTH_FILE)
        self.cycles = 0
        self.errors = 0
        self.preflight_receipt: dict[str, Any] = {}

    @property
    def lease_seconds(self) -> int:
        return int(settings.MEDIA_RENDER_LEASE_SECONDS)

    def write_health(self, status: str) -> None:
        payload = {
            "status": status,
            "worker_id": self.worker_id,
            "checked_at": _now().isoformat(),
            "checked_at_epoch": time.time(),
            "cycles": self.cycles,
            "errors": self.errors,
            "ffmpeg_version": self.preflight_receipt.get("version"),
            "hardware_adapters": self.preflight_receipt.get("hardware_adapters", []),
            "secret_returned": False,
        }
        self.health_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.health_path.with_name(f".{self.health_path.name}.tmp")
        temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.replace(temporary, self.health_path)

    async def preflight(self) -> dict[str, Any]:
        async with self.session_factory() as session:
            await session.execute(select(MediaRenderStep.id).limit(1))
        await asyncio.to_thread(self.store.preflight)
        receipt = await asyncio.to_thread(self.runtime.preflight)
        self.preflight_receipt = receipt
        return receipt

    async def reap_exhausted_leases(self, *, limit: int = 16) -> int:
        now = _now()
        async with self.session_factory() as session:
            rows = list(
                (
                    await session.scalars(
                        select(MediaRenderStep)
                        .where(
                            MediaRenderStep.status == "running",
                            MediaRenderStep.attempts >= MediaRenderStep.max_attempts,
                            MediaRenderStep.lease_expires_at < now,
                        )
                        .order_by(MediaRenderStep.created_at)
                        .with_for_update(skip_locked=True)
                        .limit(max(1, min(100, int(limit))))
                    )
                ).all()
            )
            for row in rows:
                row.status = "failed"
                row.error_code = row.error_code or "media_render_lease_exhausted"
                row.error_message = row.error_message or "Media render retry budget was exhausted."
                row.completed_at = now
                row.lease_token = None
                row.lease_owner = None
                row.lease_expires_at = None
                graph = await session.get(MediaAssetGraph, row.graph_id)
                if graph is not None:
                    graph.status = "failed"
                session.add(
                    AuditEvent(
                        organization_id=row.organization_id,
                        user_id=None,
                        action="media.render.dead_lettered",
                        resource_type="media_render_step",
                        resource_id=row.id,
                        details={
                            "attempts": row.attempts,
                            "max_attempts": row.max_attempts,
                            "fencing_token": row.fencing_token,
                            "production_modified": False,
                        },
                    )
                )
            if rows:
                await session.commit()
            return len(rows)

    async def claim(self) -> RenderClaim | None:
        await self.reap_exhausted_leases()
        now = _now()
        lease_until = now + timedelta(seconds=self.lease_seconds)
        async with self.session_factory() as session:
            dependency_edge = aliased(MediaAssetEdge)
            dependency_node = aliased(MediaAssetNode)
            blocked_dependencies = (
                select(func.count(dependency_edge.id))
                .join(dependency_node, dependency_node.id == dependency_edge.parent_node_id)
                .where(
                    dependency_edge.graph_id == MediaRenderStep.graph_id,
                    dependency_edge.child_node_id == MediaRenderStep.target_node_id,
                    dependency_node.status != "completed",
                )
                .correlate(MediaRenderStep)
                .scalar_subquery()
            )
            queued = and_(
                MediaRenderStep.status.in_(("planned", "retry_queued")),
                MediaRenderStep.attempts < MediaRenderStep.max_attempts,
                blocked_dependencies == 0,
                or_(
                    MediaRenderStep.available_at.is_(None),
                    MediaRenderStep.available_at <= now,
                ),
            )
            recovery = and_(
                MediaRenderStep.status == "running",
                MediaRenderStep.attempts < MediaRenderStep.max_attempts,
                blocked_dependencies == 0,
                MediaRenderStep.lease_expires_at < now,
            )
            dependency_edge = aliased(MediaAssetEdge)
            dependency_node = aliased(MediaAssetNode)
            blocked_by_dependency = (
                select(dependency_edge.id)
                .join(
                    dependency_node,
                    dependency_node.id == dependency_edge.parent_node_id,
                )
                .where(
                    dependency_edge.graph_id == MediaRenderStep.graph_id,
                    dependency_edge.child_node_id == MediaRenderStep.target_node_id,
                    dependency_node.status != "completed",
                )
                .correlate(MediaRenderStep)
                .exists()
            )
            row = await session.scalar(
                select(MediaRenderStep)
                .where(or_(queued, recovery), ~blocked_by_dependency)
                .order_by(MediaRenderStep.created_at, MediaRenderStep.step_key)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if row is None:
                return None
            previous_owner = row.lease_owner
            reclaimed = row.status == "running"
            token = str(uuid4())
            row.attempts += 1
            row.fencing_token += 1
            row.status = "running"
            row.lease_token = token
            row.lease_owner = self.worker_id
            row.lease_expires_at = lease_until
            row.available_at = None
            row.started_at = row.started_at or now
            row.error_code = None
            row.error_message = None
            session.add(
                AuditEvent(
                    organization_id=row.organization_id,
                    user_id=None,
                    action="media.render.claimed",
                    resource_type="media_render_step",
                    resource_id=row.id,
                    details={
                        "worker_id": self.worker_id,
                        "reclaimed": reclaimed,
                        "previous_lease_owner": previous_owner,
                        "attempt": row.attempts,
                        "fencing_token": row.fencing_token,
                        "operation": row.operation,
                    },
                )
            )
            await session.commit()
            return RenderClaim(row.id, token, row.fencing_token)

    async def renew(self, claim: RenderClaim) -> None:
        async with self.session_factory() as session:
            row = await session.scalar(
                select(MediaRenderStep)
                .where(
                    MediaRenderStep.id == claim.step_id,
                    MediaRenderStep.status == "running",
                    MediaRenderStep.lease_token == claim.lease_token,
                    MediaRenderStep.lease_owner == self.worker_id,
                    MediaRenderStep.fencing_token == claim.fencing_token,
                )
                .with_for_update()
            )
            if row is None:
                raise MediaRenderLeaseLost(claim.step_id)
            row.lease_expires_at = _now() + timedelta(seconds=self.lease_seconds)
            await session.commit()

    async def _await_with_renewal(self, task: asyncio.Task[Any], claim: RenderClaim) -> Any:
        interval = max(5.0, self.lease_seconds / 3.0)
        while True:
            done, _ = await asyncio.wait({task}, timeout=interval)
            if done:
                return task.result()
            await self.renew(claim)

    async def _load_execution(
        self, claim: RenderClaim
    ) -> tuple[MediaRenderStep, MediaAssetNode, list[MediaAssetNode]]:
        async with self.session_factory() as session:
            step = await session.scalar(
                select(MediaRenderStep).where(
                    MediaRenderStep.id == claim.step_id,
                    MediaRenderStep.status == "running",
                    MediaRenderStep.lease_token == claim.lease_token,
                    MediaRenderStep.lease_owner == self.worker_id,
                    MediaRenderStep.fencing_token == claim.fencing_token,
                )
            )
            if step is None:
                raise MediaRenderLeaseLost(claim.step_id)
            target = await session.get(MediaAssetNode, step.target_node_id)
            if target is None or target.organization_id != step.organization_id:
                raise MediaFFmpegError("media render target is unavailable")
            parent_ids = list(
                (
                    await session.scalars(
                        select(MediaAssetEdge.parent_node_id)
                        .where(
                            MediaAssetEdge.graph_id == step.graph_id,
                            MediaAssetEdge.child_node_id == target.id,
                        )
                        .order_by(MediaAssetEdge.ordinal, MediaAssetEdge.id)
                    )
                ).all()
            )
            parents: list[MediaAssetNode] = []
            for parent_id in parent_ids:
                parent = await session.get(MediaAssetNode, parent_id)
                if (
                    parent is None
                    or parent.organization_id != step.organization_id
                    or parent.status != "completed"
                    or not parent.storage_key
                    or not parent.checksum
                ):
                    raise MediaFFmpegError("media render dependency is not ready")
                parents.append(parent)
            return step, target, parents

    @staticmethod
    def _safe_suffix(key: str | None, fallback: str = ".bin") -> str:
        suffix = Path(key or "").suffix.lower()
        if re_safe_suffix(suffix):
            return suffix
        return fallback

    async def _complete(
        self,
        claim: RenderClaim,
        *,
        stored_key: str,
        stored_backend: str,
        stored_size: int,
        stored_checksum: str,
        render: MediaRenderResult,
        input_checksums: list[str],
    ) -> None:
        async with self.session_factory() as session:
            step = await session.scalar(
                select(MediaRenderStep)
                .where(
                    MediaRenderStep.id == claim.step_id,
                    MediaRenderStep.status == "running",
                    MediaRenderStep.lease_token == claim.lease_token,
                    MediaRenderStep.lease_owner == self.worker_id,
                    MediaRenderStep.fencing_token == claim.fencing_token,
                )
                .with_for_update()
            )
            if step is None:
                raise MediaRenderLeaseLost(claim.step_id)
            target = await session.scalar(
                select(MediaAssetNode)
                .where(MediaAssetNode.id == step.target_node_id)
                .with_for_update()
            )
            if target is None:
                raise MediaRenderLeaseLost(claim.step_id)
            completed_at = _now()
            target.status = "completed"
            target.storage_backend = stored_backend
            target.storage_key = stored_key
            target.checksum = stored_checksum
            target.size_bytes = stored_size
            target.media_type = output_profile(step.output_profile).media_type
            target.provenance = [
                *(target.provenance or []),
                {
                    "type": "ffmpeg-render",
                    "engine": "ffmpeg",
                    "engine_version": render.engine_version,
                    "operation": step.operation,
                    "output_profile": step.output_profile,
                    "command_hash": render.command_hash,
                    "input_checksums": input_checksums,
                    "output_checksum": stored_checksum,
                    "fencing_token": claim.fencing_token,
                    "completed_at": completed_at.isoformat(),
                },
            ]
            step.status = "completed"
            step.input_checksums = input_checksums
            step.output_checksum = stored_checksum
            step.command_hash = render.command_hash
            step.result_metadata = {
                "storage_key": stored_key,
                "storage_backend": stored_backend,
                "size_bytes": stored_size,
                "probe": _probe_summary(render.probe),
                "qa": render.qa,
                "engine_version": render.engine_version,
                "hardware_adapter": render.hardware_adapter,
            }
            step.completed_at = completed_at
            step.lease_token = None
            step.lease_owner = None
            step.lease_expires_at = None
            step.available_at = None
            step.error_code = None
            step.error_message = None
            await session.flush()
            remaining = int(
                await session.scalar(
                    select(func.count(MediaRenderStep.id)).where(
                        MediaRenderStep.graph_id == step.graph_id,
                        MediaRenderStep.status != "completed",
                    )
                )
                or 0
            )
            graph = await session.scalar(
                select(MediaAssetGraph)
                .where(MediaAssetGraph.id == step.graph_id)
                .with_for_update()
            )
            if graph is not None and remaining == 0:
                graph.status = "completed"
                completion_metadata: dict[str, Any] = {
                    "completed_at": completed_at.isoformat(),
                    "final_node_id": target.id,
                    "final_checksum": stored_checksum,
                }
                if graph.studio_asset_id:
                    asset = await session.scalar(
                        select(StudioAsset)
                        .where(
                            StudioAsset.id == graph.studio_asset_id,
                            StudioAsset.organization_id == graph.organization_id,
                        )
                        .with_for_update()
                    )
                    if asset is None:
                        raise MediaRenderLeaseLost(claim.step_id)
                    current_media = (asset.asset_metadata or {}).get("media_graph_output")
                    if not isinstance(current_media, dict) or current_media.get("graph_id") != graph.id:
                        revision_number = int(asset.current_revision) + 1
                        profile = output_profile(graph.output_profile)
                        filename = f"{slug(graph.title)}-media-v{graph.graph_version}.{profile.extension}"
                        media_metadata = {
                            "graph_id": graph.id,
                            "graph_version": graph.graph_version,
                            "storage_backend": stored_backend,
                            "storage_key": stored_key,
                            "engine": "ffmpeg",
                            "engine_version": render.engine_version,
                            "output_profile": graph.output_profile,
                            "command_hash": render.command_hash,
                            "probe": _probe_summary(render.probe),
                            "qa": render.qa,
                        }
                        revision = StudioAssetRevision(
                            id=uuid_str(),
                            organization_id=graph.organization_id,
                            asset_id=asset.id,
                            job_id=graph.studio_job_id or asset.job_id,
                            created_by_id=graph.created_by_id,
                            revision_number=revision_number,
                            filename=filename,
                            media_type=target.media_type or profile.media_type,
                            storage_path=stored_key,
                            checksum=stored_checksum,
                            size_bytes=stored_size,
                            change_note=f"Phase 36D rendered media graph v{graph.graph_version}",
                            revision_metadata={"media_graph_output": media_metadata},
                            status="active",
                        )
                        session.add(revision)
                        asset.current_revision = revision_number
                        asset.filename = filename
                        asset.media_type = target.media_type or profile.media_type
                        asset.storage_path = stored_key
                        asset.checksum = stored_checksum
                        asset.size_bytes = stored_size
                        asset.asset_metadata = {
                            **(asset.asset_metadata or {}),
                            "media_graph_output": media_metadata,
                        }
                        completion_metadata.update(
                            {
                                "studio_asset_id": asset.id,
                                "studio_revision_id": revision.id,
                                "studio_revision_number": revision_number,
                            }
                        )
                graph.graph_metadata = {
                    **(graph.graph_metadata or {}),
                    **completion_metadata,
                }
            session.add(
                AuditEvent(
                    organization_id=step.organization_id,
                    user_id=None,
                    action="media.render.completed",
                    resource_type="media_render_step",
                    resource_id=step.id,
                    details={
                        "graph_id": step.graph_id,
                        "target_node_id": target.id,
                        "output_checksum": stored_checksum,
                        "command_hash": render.command_hash,
                        "fencing_token": claim.fencing_token,
                    },
                )
            )
            await session.commit()

    async def _fail(self, claim: RenderClaim, code: str, message: str) -> None:
        async with self.session_factory() as session:
            step = await session.scalar(
                select(MediaRenderStep)
                .where(
                    MediaRenderStep.id == claim.step_id,
                    MediaRenderStep.status == "running",
                    MediaRenderStep.lease_token == claim.lease_token,
                    MediaRenderStep.lease_owner == self.worker_id,
                    MediaRenderStep.fencing_token == claim.fencing_token,
                )
                .with_for_update()
            )
            if step is None:
                raise MediaRenderLeaseLost(claim.step_id)
            terminal = step.attempts >= step.max_attempts
            step.status = "failed" if terminal else "retry_queued"
            step.error_code = code
            step.error_message = message
            step.completed_at = _now() if terminal else None
            step.available_at = None if terminal else _now() + timedelta(
                seconds=min(60, 2 ** max(1, step.attempts))
            )
            step.lease_token = None
            step.lease_owner = None
            step.lease_expires_at = None
            if terminal:
                graph = await session.get(MediaAssetGraph, step.graph_id)
                if graph is not None:
                    graph.status = "failed"
            session.add(
                AuditEvent(
                    organization_id=step.organization_id,
                    user_id=None,
                    action="media.render.failed" if terminal else "media.render.retry_scheduled",
                    resource_type="media_render_step",
                    resource_id=step.id,
                    details={
                        "error_code": code,
                        "attempt": step.attempts,
                        "terminal": terminal,
                        "fencing_token": claim.fencing_token,
                    },
                )
            )
            await session.commit()

    async def execute(self, claim: RenderClaim) -> None:
        output_key: str | None = None
        try:
            step, target, parents = await self._load_execution(claim)
            root = Path(settings.MEDIA_RENDER_TEMP_ROOT).resolve()
            root.mkdir(parents=True, exist_ok=True, mode=0o700)
            workdir = root / f"{claim.step_id}-f{claim.fencing_token}"
            if workdir.exists():
                shutil.rmtree(workdir)
            workdir.mkdir(mode=0o700)
            input_paths: list[Path] = []
            input_checksums: list[str] = []
            for index, parent in enumerate(parents):
                storage_key = parent.storage_key
                if not storage_key:
                    raise MediaStorageError("media dependency storage key is missing")
                body = await asyncio.to_thread(
                    self.store.get_bytes,
                    storage_key,
                    max_bytes=settings.MEDIA_MAX_OBJECT_BYTES,
                )
                digest = hashlib.sha256(body).hexdigest()
                if digest != parent.checksum:
                    raise MediaStorageError("media dependency checksum verification failed")
                path = workdir / f"input-{index:03d}{self._safe_suffix(storage_key)}"
                path.write_bytes(body)
                os.chmod(path, 0o600)
                input_paths.append(path)
                input_checksums.append(digest)
            profile = output_profile(step.output_profile)
            output_path = workdir / f"output.{profile.extension}"
            metadata = dict(target.operation_metadata or {})
            render_task = asyncio.create_task(
                asyncio.to_thread(
                    self.runtime.render,
                    operation=step.operation,
                    profile_id=step.output_profile,
                    input_paths=input_paths,
                    output_path=output_path,
                    metadata=metadata,
                    input_checksums=input_checksums,
                    hardware_adapter=step.hardware_adapter,
                )
            )
            render: MediaRenderResult = await self._await_with_renewal(render_task, claim)
            await self.renew(claim)
            body = output_path.read_bytes()
            output_key = (
                f"media/{step.organization_id}/{step.graph_id}/{target.logical_key}/"
                f"r{target.revision}/f{claim.fencing_token}-{render.command_hash[:16]}.{profile.extension}"
            )
            upload_task = asyncio.create_task(
                asyncio.to_thread(
                    self.store.put_bytes,
                    output_key,
                    body,
                    profile.media_type,
                    metadata={
                        "graph-id": step.graph_id,
                        "node-id": target.id,
                        "revision": str(target.revision),
                        "command-hash": render.command_hash,
                    },
                )
            )
            stored = await self._await_with_renewal(upload_task, claim)
            await self._complete(
                claim,
                stored_key=stored.key,
                stored_backend=stored.backend,
                stored_size=stored.size_bytes,
                stored_checksum=stored.sha256,
                render=render,
                input_checksums=input_checksums,
            )
        except MediaRenderLeaseLost:
            if output_key:
                await asyncio.to_thread(self.store.delete, output_key)
            raise
        except (MediaFFmpegError, MediaStorageError, OSError, ValueError) as exc:
            code = "MEDIA_RENDER_FAILED"
            logger.error("Media render step failed", step_id=claim.step_id, error_type=type(exc).__name__)
            try:
                await self._fail(claim, code, str(exc)[:500])
            except MediaRenderLeaseLost:
                if output_key:
                    await asyncio.to_thread(self.store.delete, output_key)
                raise
        finally:
            root = Path(settings.MEDIA_RENDER_TEMP_ROOT).resolve()
            workdir = root / f"{claim.step_id}-f{claim.fencing_token}"
            shutil.rmtree(workdir, ignore_errors=True)

    async def run_once(self) -> bool:
        claim = await self.claim()
        if claim is None:
            return False
        await self.execute(claim)
        self.cycles += 1
        self.write_health("running")
        return True

    async def run_forever(self) -> None:
        await self.preflight()
        self.write_health("running")
        while not self.stop_event.is_set():
            try:
                processed = await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.errors += 1
                logger.error("Media render worker cycle failed", error_type=type(exc).__name__)
                self.write_health("degraded")
                processed = False
            if processed:
                continue
            try:
                await asyncio.wait_for(
                    self.stop_event.wait(), timeout=float(settings.MEDIA_RENDER_POLL_SECONDS)
                )
            except TimeoutError:
                self.write_health("running")
        self.write_health("stopped")


def re_safe_suffix(value: str) -> bool:
    return bool(value) and len(value) <= 10 and value[0] == "." and value[1:].isalnum()


def healthcheck(path: str | Path | None = None, maximum_age_seconds: float = 90.0) -> int:
    target = Path(path or settings.MEDIA_RENDER_WORKER_HEALTH_FILE)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
        age = time.time() - float(payload["checked_at_epoch"])
        healthy = (
            payload.get("status") == "running"
            and payload.get("ffmpeg_version") == settings.MEDIA_FFMPEG_TARGET_VERSION
            and 0 <= age <= maximum_age_seconds
        )
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        healthy = False
    return 0 if healthy else 1


async def async_main(*, once: bool = False) -> int:
    worker = MediaRenderWorker()
    if once:
        await worker.preflight()
        await worker.run_once()
        return 0
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, worker.stop_event.set)
    await worker.run_forever()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--healthcheck", action="store_true")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if args.healthcheck:
        return healthcheck()
    setup_logging()
    return asyncio.run(async_main(once=args.once))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
