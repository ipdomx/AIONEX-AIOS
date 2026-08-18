"""Durable local Sharp derivative worker for Phase 36E.

The worker only claims ``MediaRenderStep(engine=sharp)`` records and is disabled by
default. It never invokes an image provider or reads provider credentials.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import socket
import time
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
from app.services.design_editable_source import (
    DesignEditableSourceError,
    build_rendered_editable_svg,
)
from app.services.design_image_derivatives import (
    DesignImageDerivativeError,
    SharpDerivativeRuntime,
    SharpDerivativeSpec,
)
from app.services.image_raster_validation import ImageRasterValidationError, inspect_raster
from app.services.media_orchestrator import SHARP_TARGET_VERSION
from app.services.media_storage import MediaObjectStore, MediaStorageError, media_object_store
from app.services.production_studio import slug
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import aliased

logger = get_logger(__name__)
_CONTENT_TO_FORMAT = {"image/png": "png", "image/jpeg": "jpeg", "image/webp": "webp"}
_SUFFIXES = {"png": "png", "jpeg": "jpg", "webp": "webp"}


class DesignImageDerivativeLeaseLost(RuntimeError):
    """A stale Sharp worker attempted to mutate a reclaimed derivative step."""


@dataclass(frozen=True, slots=True)
class DerivativeClaim:
    step_id: str
    lease_token: str
    fencing_token: int


def _now() -> datetime:
    return datetime.now(UTC)


class DesignImageDerivativeWorker:
    def __init__(
        self,
        *,
        store: MediaObjectStore | None = None,
        runtime: SharpDerivativeRuntime | None = None,
        worker_id: str | None = None,
    ) -> None:
        configured = (worker_id or settings.DESIGN_IMAGE_DERIVATIVE_WORKER_ID).strip()
        self.worker_id = configured or f"design-image-derivative:{socket.gethostname()}"
        self.store = store or media_object_store()
        self.runtime = runtime or SharpDerivativeRuntime()
        self.health_path = Path(settings.DESIGN_IMAGE_DERIVATIVE_WORKER_HEALTH_FILE)
        self.cycles = 0
        self.errors = 0
        self.preflight_receipt: dict[str, Any] = {}

    @property
    def lease_seconds(self) -> int:
        return int(settings.DESIGN_IMAGE_DERIVATIVE_LEASE_SECONDS)

    def write_health(self, status: str) -> None:
        payload = {
            "status": status,
            "worker_id": self.worker_id,
            "enabled": bool(settings.DESIGN_IMAGE_DERIVATIVE_ENABLED),
            "checked_at": _now().isoformat(),
            "checked_at_epoch": time.time(),
            "cycles": self.cycles,
            "errors": self.errors,
            "engine": self.preflight_receipt.get("engine"),
            "engine_version": self.preflight_receipt.get("engine_version"),
            "node_version": self.preflight_receipt.get("node_version"),
            "secret_returned": False,
        }
        self.health_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.health_path.with_name(f".{self.health_path.name}.tmp")
        temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.replace(temporary, self.health_path)

    async def preflight(self) -> dict[str, Any]:
        await asyncio.to_thread(self.store.preflight)
        async with SessionLocal() as session:
            await session.execute(select(MediaRenderStep.id).limit(1))
        receipt = await asyncio.to_thread(self.runtime.preflight)
        self.preflight_receipt = receipt
        return receipt

    async def reap_exhausted_leases(self, *, limit: int = 16) -> int:
        now = _now()
        async with SessionLocal() as session:
            rows = list(
                (
                    await session.scalars(
                        select(MediaRenderStep)
                        .where(
                            MediaRenderStep.engine == "sharp",
                            MediaRenderStep.operation == "design-image-derivative",
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
                row.error_code = row.error_code or "design_image_derivative_lease_exhausted"
                row.error_message = row.error_message or "Image derivative retry budget was exhausted."
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
                        action="design.image.derivative.dead_lettered",
                        resource_type="media_render_step",
                        resource_id=row.id,
                        details={
                            "attempts": row.attempts,
                            "max_attempts": row.max_attempts,
                            "fencing_token": row.fencing_token,
                            "engine": "sharp",
                        },
                    )
                )
            if rows:
                await session.commit()
            return len(rows)

    async def claim(self) -> DerivativeClaim | None:
        if not settings.DESIGN_IMAGE_DERIVATIVE_ENABLED:
            return None
        await self.reap_exhausted_leases()
        now = _now()
        dependency_edge = aliased(MediaAssetEdge)
        dependency_node = aliased(MediaAssetNode)
        blocked = (
            select(dependency_edge.id)
            .join(dependency_node, dependency_node.id == dependency_edge.parent_node_id)
            .where(
                dependency_edge.graph_id == MediaRenderStep.graph_id,
                dependency_edge.child_node_id == MediaRenderStep.target_node_id,
                dependency_node.status != "completed",
            )
            .correlate(MediaRenderStep)
            .exists()
        )
        queued = and_(
            MediaRenderStep.engine == "sharp",
            MediaRenderStep.operation == "design-image-derivative",
            MediaRenderStep.status.in_(("planned", "retry_queued")),
            MediaRenderStep.attempts < MediaRenderStep.max_attempts,
            or_(MediaRenderStep.available_at.is_(None), MediaRenderStep.available_at <= now),
        )
        recovery = and_(
            MediaRenderStep.engine == "sharp",
            MediaRenderStep.operation == "design-image-derivative",
            MediaRenderStep.status == "running",
            MediaRenderStep.attempts < MediaRenderStep.max_attempts,
            MediaRenderStep.lease_expires_at < now,
        )
        async with SessionLocal() as session:
            row = await session.scalar(
                select(MediaRenderStep)
                .where(or_(queued, recovery), ~blocked)
                .order_by(MediaRenderStep.created_at, MediaRenderStep.step_key)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if row is None:
                return None
            previous_owner = row.lease_owner
            reclaimed = row.status == "running"
            token = str(uuid4())
            row.status = "running"
            row.attempts += 1
            row.fencing_token += 1
            row.lease_token = token
            row.lease_owner = self.worker_id
            row.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
            row.available_at = None
            row.started_at = row.started_at or now
            row.error_code = None
            row.error_message = None
            session.add(
                AuditEvent(
                    organization_id=row.organization_id,
                    user_id=None,
                    action="design.image.derivative.claimed",
                    resource_type="media_render_step",
                    resource_id=row.id,
                    details={
                        "worker_id": self.worker_id,
                        "reclaimed": reclaimed,
                        "previous_lease_owner": previous_owner,
                        "attempt": row.attempts,
                        "fencing_token": row.fencing_token,
                        "engine": "sharp",
                    },
                )
            )
            await session.commit()
            return DerivativeClaim(row.id, token, int(row.fencing_token))

    async def renew(self, claim: DerivativeClaim) -> None:
        async with SessionLocal() as session:
            row = await session.scalar(
                select(MediaRenderStep)
                .where(
                    MediaRenderStep.id == claim.step_id,
                    MediaRenderStep.engine == "sharp",
                    MediaRenderStep.status == "running",
                    MediaRenderStep.lease_token == claim.lease_token,
                    MediaRenderStep.lease_owner == self.worker_id,
                    MediaRenderStep.fencing_token == claim.fencing_token,
                )
                .with_for_update()
            )
            if row is None:
                raise DesignImageDerivativeLeaseLost(claim.step_id)
            row.lease_expires_at = _now() + timedelta(seconds=self.lease_seconds)
            await session.commit()

    async def _await_with_renewal(self, task: asyncio.Task[Any], claim: DerivativeClaim) -> Any:
        interval = max(5.0, self.lease_seconds / 3.0)
        while True:
            done, _ = await asyncio.wait({task}, timeout=interval)
            if done:
                return task.result()
            await self.renew(claim)

    async def _load_execution(
        self, claim: DerivativeClaim
    ) -> tuple[MediaRenderStep, MediaAssetNode, MediaAssetNode, SharpDerivativeSpec]:
        async with SessionLocal() as session:
            step = await session.scalar(
                select(MediaRenderStep).where(
                    MediaRenderStep.id == claim.step_id,
                    MediaRenderStep.engine == "sharp",
                    MediaRenderStep.operation == "design-image-derivative",
                    MediaRenderStep.status == "running",
                    MediaRenderStep.lease_token == claim.lease_token,
                    MediaRenderStep.lease_owner == self.worker_id,
                    MediaRenderStep.fencing_token == claim.fencing_token,
                )
            )
            if step is None or step.engine_version != SHARP_TARGET_VERSION:
                raise DesignImageDerivativeLeaseLost(claim.step_id)
            target = await session.get(MediaAssetNode, step.target_node_id)
            if target is None or target.organization_id != step.organization_id:
                raise DesignImageDerivativeError("image derivative target is unavailable")
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
            if len(parent_ids) != 1:
                raise DesignImageDerivativeError("image derivative requires exactly one source node")
            parent = await session.get(MediaAssetNode, parent_ids[0])
            if (
                parent is None
                or parent.organization_id != step.organization_id
                or parent.status != "completed"
                or not parent.storage_key
                or not parent.checksum
                or parent.media_type not in _CONTENT_TO_FORMAT
            ):
                raise DesignImageDerivativeError("image derivative source is unavailable")
            options = dict(target.operation_metadata or {})
            spec = SharpDerivativeSpec(
                width=int(options.get("width") or 0),
                height=int(options.get("height") or 0),
                output_format=str(options.get("output_format") or ""),
                fit=str(options.get("fit") or "cover"),
                position=str(options.get("position") or "centre"),
            )
            return step, target, parent, spec

    async def _fail(self, claim: DerivativeClaim, *, code: str, message: str) -> None:
        async with SessionLocal() as session:
            row = await session.scalar(
                select(MediaRenderStep)
                .where(
                    MediaRenderStep.id == claim.step_id,
                    MediaRenderStep.engine == "sharp",
                    MediaRenderStep.status == "running",
                    MediaRenderStep.lease_token == claim.lease_token,
                    MediaRenderStep.lease_owner == self.worker_id,
                    MediaRenderStep.fencing_token == claim.fencing_token,
                )
                .with_for_update()
            )
            if row is None:
                raise DesignImageDerivativeLeaseLost(claim.step_id)
            terminal = int(row.attempts) >= int(row.max_attempts)
            row.status = "failed" if terminal else "retry_queued"
            row.error_code = code[:120]
            row.error_message = message[:500]
            row.completed_at = _now() if terminal else None
            row.available_at = None if terminal else _now() + timedelta(seconds=min(60, 2 ** row.attempts))
            row.lease_token = None
            row.lease_owner = None
            row.lease_expires_at = None
            if terminal:
                graph = await session.get(MediaAssetGraph, row.graph_id)
                if graph is not None:
                    graph.status = "failed"
            session.add(
                AuditEvent(
                    organization_id=row.organization_id,
                    user_id=None,
                    action=(
                        "design.image.derivative.failed"
                        if terminal
                        else "design.image.derivative.retry_scheduled"
                    ),
                    resource_type="media_render_step",
                    resource_id=row.id,
                    details={
                        "error_code": row.error_code,
                        "attempt": row.attempts,
                        "terminal": terminal,
                        "fencing_token": claim.fencing_token,
                        "engine": "sharp",
                    },
                )
            )
            await session.commit()

    async def _materialize_editable_source(
        self,
        claim: DerivativeClaim,
        *,
        graph_id: str,
        organization_id: str,
        graph_version: int,
        pipeline: dict[str, Any],
        raster_body: bytes,
        raster_media_type: str,
        raster_checksum: str,
    ) -> tuple[str, dict[str, Any]]:
        contract = pipeline.get("editable_contract")
        if not isinstance(contract, dict):
            raise DesignImageDerivativeError("image derivative editable-source contract is unavailable")
        build_task = asyncio.create_task(
            asyncio.to_thread(
                build_rendered_editable_svg,
                contract=contract,
                raster_body=raster_body,
                raster_media_type=raster_media_type,
                raster_checksum=raster_checksum,
            )
        )
        try:
            rendered = await self._await_with_renewal(build_task, claim)
        except DesignEditableSourceError as exc:
            raise DesignImageDerivativeError(str(exc)) from exc
        if rendered.size_bytes > int(settings.MEDIA_MAX_OBJECT_BYTES):
            raise DesignImageDerivativeError("editable source exceeds the governed media-object limit")
        key = (
            f"media/{organization_id}/{graph_id}/editable/"
            f"v{graph_version}-{rendered.checksum[:16]}.svg"
        )
        upload_task = asyncio.create_task(
            asyncio.to_thread(
                self.store.put_bytes,
                key,
                rendered.body,
                rendered.media_type,
                metadata={
                    "graph-id": graph_id,
                    "base-raster-sha256": raster_checksum,
                    "editable-schema": rendered.schema,
                },
            )
        )
        stored = await self._await_with_renewal(upload_task, claim)
        if stored.sha256 != rendered.checksum or stored.size_bytes != rendered.size_bytes:
            await asyncio.to_thread(self.store.delete, key)
            raise DesignImageDerivativeError("editable source storage verification failed")
        return key, {
            "schema": rendered.schema,
            "media_type": rendered.media_type,
            "storage_backend": stored.backend,
            "storage_key": stored.key,
            "checksum": stored.sha256,
            "size_bytes": stored.size_bytes,
            "base_raster_checksum": raster_checksum,
        }

    async def _prepare_editable_source_for_completion(
        self,
        claim: DerivativeClaim,
        *,
        step: MediaRenderStep,
        target: MediaAssetNode,
        result_body: bytes,
        result_content_type: str,
        result_checksum: str,
    ) -> tuple[str, dict[str, Any]] | None:
        primary_storage_key: str | None = None
        raster_body: bytes | None = None
        async with SessionLocal() as session:
            live_step = await session.scalar(
                select(MediaRenderStep).where(
                    MediaRenderStep.id == claim.step_id,
                    MediaRenderStep.engine == "sharp",
                    MediaRenderStep.status == "running",
                    MediaRenderStep.lease_token == claim.lease_token,
                    MediaRenderStep.lease_owner == self.worker_id,
                    MediaRenderStep.fencing_token == claim.fencing_token,
                )
            )
            if live_step is None:
                raise DesignImageDerivativeLeaseLost(claim.step_id)
            graph = await session.get(MediaAssetGraph, live_step.graph_id)
            if graph is None or graph.organization_id != live_step.organization_id:
                raise DesignImageDerivativeLeaseLost(claim.step_id)
            pipeline = (graph.graph_metadata or {}).get("design_image_pipeline")
            if not isinstance(pipeline, dict):
                raise DesignImageDerivativeError("image derivative graph lacks pipeline authority")
            other_incomplete = int(
                await session.scalar(
                    select(func.count(MediaAssetNode.id)).where(
                        MediaAssetNode.graph_id == graph.id,
                        MediaAssetNode.id != target.id,
                        MediaAssetNode.status != "completed",
                    )
                )
                or 0
            )
            if other_incomplete != 0:
                return None
            primary_id = str(pipeline.get("primary_derivative_node_id") or "")
            if primary_id == target.id:
                raster_body = result_body
                raster_media_type = result_content_type
                raster_checksum = result_checksum
            else:
                primary = await session.get(MediaAssetNode, primary_id)
                if (
                    primary is None
                    or primary.graph_id != graph.id
                    or primary.organization_id != graph.organization_id
                    or primary.status != "completed"
                    or not primary.storage_key
                    or not primary.checksum
                    or not primary.media_type
                ):
                    raise DesignImageDerivativeError("image derivative editable-source raster is unavailable")
                primary_storage_key = primary.storage_key
                raster_media_type = primary.media_type
                raster_checksum = primary.checksum
            graph_id = graph.id
            organization_id = graph.organization_id
            graph_version = int(graph.graph_version)
            pipeline_copy = dict(pipeline)

        if raster_body is None:
            assert primary_storage_key is not None
            load_task = asyncio.create_task(
                asyncio.to_thread(
                    self.store.get_bytes,
                    primary_storage_key,
                    max_bytes=min(int(settings.MEDIA_MAX_OBJECT_BYTES), 32 * 1024 * 1024),
                )
            )
            raster_body = await self._await_with_renewal(load_task, claim)
        return await self._materialize_editable_source(
            claim,
            graph_id=graph_id,
            organization_id=organization_id,
            graph_version=graph_version,
            pipeline=pipeline_copy,
            raster_body=raster_body,
            raster_media_type=raster_media_type,
            raster_checksum=raster_checksum,
        )

    async def _complete(
        self,
        claim: DerivativeClaim,
        *,
        stored_key: str,
        stored_backend: str,
        stored_size: int,
        stored_checksum: str,
        result_metadata: dict[str, Any],
        input_checksum: str,
        command_hash: str,
        content_type: str,
        editable_source: dict[str, Any] | None,
    ) -> None:
        async with SessionLocal() as session:
            step = await session.scalar(
                select(MediaRenderStep)
                .where(
                    MediaRenderStep.id == claim.step_id,
                    MediaRenderStep.engine == "sharp",
                    MediaRenderStep.status == "running",
                    MediaRenderStep.lease_token == claim.lease_token,
                    MediaRenderStep.lease_owner == self.worker_id,
                    MediaRenderStep.fencing_token == claim.fencing_token,
                )
                .with_for_update()
            )
            if step is None:
                raise DesignImageDerivativeLeaseLost(claim.step_id)
            target = await session.scalar(
                select(MediaAssetNode)
                .where(MediaAssetNode.id == step.target_node_id)
                .with_for_update()
            )
            graph = await session.scalar(
                select(MediaAssetGraph)
                .where(MediaAssetGraph.id == step.graph_id)
                .with_for_update()
            )
            if target is None or graph is None:
                raise DesignImageDerivativeLeaseLost(claim.step_id)
            completed = _now()
            target.status = "completed"
            target.storage_backend = stored_backend
            target.storage_key = stored_key
            target.checksum = stored_checksum
            target.size_bytes = stored_size
            target.media_type = content_type
            target.provenance = [
                *(target.provenance or []),
                {
                    "type": "sharp-image-derivative",
                    "engine": "sharp",
                    "engine_version": SHARP_TARGET_VERSION,
                    "input_checksum": input_checksum,
                    "output_checksum": stored_checksum,
                    "command_hash": command_hash,
                    "fencing_token": claim.fencing_token,
                    "completed_at": completed.isoformat(),
                },
            ]
            step.status = "completed"
            step.input_checksums = [input_checksum]
            step.output_checksum = stored_checksum
            step.command_hash = command_hash
            step.result_metadata = {
                "storage_key": stored_key,
                "storage_backend": stored_backend,
                "size_bytes": stored_size,
                **result_metadata,
            }
            step.completed_at = completed
            step.lease_token = None
            step.lease_owner = None
            step.lease_expires_at = None
            step.available_at = None
            step.error_code = None
            step.error_message = None
            await session.flush()

            incomplete_nodes = int(
                await session.scalar(
                    select(func.count(MediaAssetNode.id)).where(
                        MediaAssetNode.graph_id == graph.id,
                        MediaAssetNode.status != "completed",
                    )
                )
                or 0
            )
            if incomplete_nodes != 0 and editable_source is not None:
                raise DesignImageDerivativeError(
                    "image derivative editable source was prepared before the graph was final"
                )
            if incomplete_nodes == 0:
                pipeline = (graph.graph_metadata or {}).get("design_image_pipeline")
                if not isinstance(pipeline, dict):
                    raise DesignImageDerivativeError("image derivative graph lacks pipeline authority")
                primary_id = str(pipeline.get("primary_derivative_node_id") or "")
                derivative_ids = [str(item) for item in pipeline.get("derivative_node_ids") or []]
                primary = await session.get(MediaAssetNode, primary_id)
                if (
                    primary is None
                    or primary.graph_id != graph.id
                    or primary.organization_id != graph.organization_id
                    or primary.status != "completed"
                    or not primary.storage_key
                    or not primary.checksum
                    or not primary.media_type
                ):
                    raise DesignImageDerivativeError("image derivative primary output is unavailable")
                manifest: list[dict[str, Any]] = []
                for node_id in derivative_ids:
                    node = await session.get(MediaAssetNode, node_id)
                    if (
                        node is None
                        or node.graph_id != graph.id
                        or node.status != "completed"
                        or not node.storage_key
                        or not node.checksum
                    ):
                        raise DesignImageDerivativeError("image derivative manifest is incomplete")
                    options = dict(node.operation_metadata or {})
                    manifest.append(
                        {
                            "node_id": node.id,
                            "preset_id": options.get("preset_id"),
                            "output_format": options.get("output_format"),
                            "width": options.get("width"),
                            "height": options.get("height"),
                            "storage_backend": node.storage_backend,
                            "storage_key": node.storage_key,
                            "checksum": node.checksum,
                            "size_bytes": node.size_bytes,
                        }
                    )
                graph.status = "completed"
                graph.graph_metadata = {
                    **(graph.graph_metadata or {}),
                    "completed_at": completed.isoformat(),
                    "final_node_id": primary.id,
                    "final_checksum": primary.checksum,
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
                        raise DesignImageDerivativeError("image derivative Studio asset is unavailable")
                    current = (asset.asset_metadata or {}).get("design_image_pipeline_output")
                    if not isinstance(current, dict) or current.get("graph_id") != graph.id:
                        route = pipeline.get("route") if isinstance(pipeline.get("route"), dict) else {}
                        output_format = str((primary.operation_metadata or {}).get("output_format") or "png")
                        filename = (
                            f"{slug(graph.title)}-design-v{graph.graph_version}."
                            f"{_SUFFIXES.get(output_format, 'bin')}"
                        )
                        if editable_source is None:
                            raise DesignImageDerivativeError(
                                "image derivative editable source was not materialized before finalization"
                            )
                        if (
                            editable_source.get("base_raster_checksum") != primary.checksum
                            or editable_source.get("media_type") != "image/svg+xml"
                            or not editable_source.get("storage_key")
                            or not editable_source.get("checksum")
                        ):
                            raise DesignImageDerivativeError("image derivative editable-source evidence is invalid")
                        graph.graph_metadata = {
                            **(graph.graph_metadata or {}),
                            "editable_source_checksum": editable_source["checksum"],
                            "editable_source_size_bytes": editable_source["size_bytes"],
                        }
                        metadata = {
                            "graph_id": graph.id,
                            "graph_version": graph.graph_version,
                            "primary_node_id": primary.id,
                            "storage_backend": primary.storage_backend,
                            "storage_key": primary.storage_key,
                            "engine": "sharp",
                            "engine_version": SHARP_TARGET_VERSION,
                            "route": route,
                            "derivatives": manifest,
                            "editable_source": editable_source,
                        }
                        revision_number = int(asset.current_revision) + 1
                        revision = StudioAssetRevision(
                            id=uuid_str(),
                            organization_id=graph.organization_id,
                            asset_id=asset.id,
                            job_id=graph.studio_job_id or asset.job_id,
                            created_by_id=graph.created_by_id,
                            revision_number=revision_number,
                            filename=filename,
                            media_type=primary.media_type,
                            storage_path=primary.storage_key,
                            checksum=primary.checksum,
                            size_bytes=int(primary.size_bytes or 0),
                            change_note=f"Phase 36E responsive design graph v{graph.graph_version}",
                            revision_metadata={"design_image_pipeline_output": metadata},
                            status="active",
                        )
                        session.add(revision)
                        asset.current_revision = revision_number
                        asset.filename = filename
                        asset.media_type = primary.media_type
                        asset.storage_path = primary.storage_key
                        asset.checksum = primary.checksum
                        asset.size_bytes = int(primary.size_bytes or 0)
                        asset.asset_metadata = {
                            **(asset.asset_metadata or {}),
                            "design_image_pipeline_output": metadata,
                        }
                        session.add(
                            AuditEvent(
                                organization_id=graph.organization_id,
                                user_id=None,
                                action="design.image.editable_source.materialized",
                                resource_type="media_asset_graph",
                                resource_id=graph.id,
                                details={
                                    "checksum": editable_source["checksum"],
                                    "size_bytes": editable_source["size_bytes"],
                                    "schema": editable_source["schema"],
                                    "base_raster_checksum": primary.checksum,
                                },
                            )
                        )
            session.add(
                AuditEvent(
                    organization_id=step.organization_id,
                    user_id=None,
                    action="design.image.derivative.completed",
                    resource_type="media_render_step",
                    resource_id=step.id,
                    details={
                        "graph_id": step.graph_id,
                        "target_node_id": target.id,
                        "output_checksum": stored_checksum,
                        "command_hash": command_hash,
                        "fencing_token": claim.fencing_token,
                        "engine": "sharp",
                    },
                )
            )
            await session.commit()

    async def execute(self, claim: DerivativeClaim) -> None:
        output_key: str | None = None
        editable_cleanup_key: str | None = None
        try:
            step, target, parent, spec = await self._load_execution(claim)
            assert parent.storage_key and parent.checksum and parent.media_type
            body = await asyncio.to_thread(
                self.store.get_bytes,
                parent.storage_key,
                max_bytes=settings.MEDIA_MAX_OBJECT_BYTES,
            )
            await self.renew(claim)
            render_task = asyncio.create_task(
                asyncio.to_thread(
                    self.runtime.render,
                    source_body=body,
                    source_format=_CONTENT_TO_FORMAT[parent.media_type],
                    source_checksum=parent.checksum,
                    spec=spec,
                )
            )
            result = await self._await_with_renewal(render_task, claim)
            if (
                result.output_format != spec.output_format
                or result.width != spec.width
                or result.height != spec.height
                or result.content_type != target.media_type
                or result.size_bytes != len(result.body)
                or result.sha256 != hashlib.sha256(result.body).hexdigest()
            ):
                raise DesignImageDerivativeError("image derivative runtime result contract is invalid")
            try:
                width, height = inspect_raster(result.body, result.output_format)
            except ImageRasterValidationError as exc:
                raise DesignImageDerivativeError("image derivative runtime output is not a valid raster") from exc
            if width != spec.width or height != spec.height:
                raise DesignImageDerivativeError("image derivative raster dimensions do not match the durable plan")
            await self.renew(claim)
            output_key = (
                f"media/{step.organization_id}/design/{step.graph_id}/{target.logical_key}/"
                f"r{target.revision}/f{claim.fencing_token}-{result.command_hash[:16]}."
                f"{_SUFFIXES[result.output_format]}"
            )
            upload_task = asyncio.create_task(
                asyncio.to_thread(
                    self.store.put_bytes,
                    output_key,
                    result.body,
                    result.content_type,
                    metadata={
                        "graph-id": step.graph_id,
                        "node-id": target.id,
                        "engine": "sharp",
                        "engine-version": SHARP_TARGET_VERSION,
                        "command-hash": result.command_hash,
                    },
                )
            )
            stored = await self._await_with_renewal(upload_task, claim)
            prepared = await self._prepare_editable_source_for_completion(
                claim,
                step=step,
                target=target,
                result_body=result.body,
                result_content_type=result.content_type,
                result_checksum=result.sha256,
            )
            editable_source: dict[str, Any] | None = None
            if prepared is not None:
                editable_cleanup_key, editable_source = prepared
            await self.renew(claim)
            await self._complete(
                claim,
                stored_key=stored.key,
                stored_backend=stored.backend,
                stored_size=stored.size_bytes,
                stored_checksum=stored.sha256,
                result_metadata=result.metadata,
                input_checksum=result.input_sha256,
                command_hash=result.command_hash,
                content_type=result.content_type,
                editable_source=editable_source,
            )
            editable_cleanup_key = None
        except DesignImageDerivativeLeaseLost:
            if editable_cleanup_key:
                await asyncio.to_thread(self.store.delete, editable_cleanup_key)
            if output_key:
                await asyncio.to_thread(self.store.delete, output_key)
            raise
        except (DesignImageDerivativeError, MediaStorageError, OSError, ValueError) as exc:
            if editable_cleanup_key:
                await asyncio.to_thread(self.store.delete, editable_cleanup_key)
            if output_key:
                await asyncio.to_thread(self.store.delete, output_key)
            logger.error(
                "Design image derivative failed",
                step_id=claim.step_id,
                error_type=type(exc).__name__,
            )
            await self._fail(
                claim,
                code="DESIGN_IMAGE_DERIVATIVE_FAILED",
                message=str(exc) or "Image derivative execution failed",
            )

    async def run_once(self) -> bool:
        if not settings.DESIGN_IMAGE_DERIVATIVE_ENABLED:
            self.write_health("disabled")
            return False
        claim = await self.claim()
        if claim is None:
            self.write_health("healthy")
            return False
        try:
            await self.execute(claim)
            self.cycles += 1
            self.write_health("healthy")
            return True
        except DesignImageDerivativeLeaseLost:
            self.errors += 1
            self.write_health("degraded")
            return True
        except Exception:
            self.errors += 1
            logger.exception("Design image derivative worker cycle failed", extra={"step_id": claim.step_id})
            self.write_health("degraded")
            return True

    async def run_forever(self) -> None:
        await self.preflight()
        self.write_health("healthy" if settings.DESIGN_IMAGE_DERIVATIVE_ENABLED else "disabled")
        while True:
            worked = await self.run_once()
            if not worked:
                await asyncio.sleep(int(settings.DESIGN_IMAGE_DERIVATIVE_POLL_SECONDS))


def healthcheck() -> int:
    path = Path(settings.DESIGN_IMAGE_DERIVATIVE_WORKER_HEALTH_FILE)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        age = time.time() - float(payload["checked_at_epoch"])
        status = str(payload.get("status") or "")
        version_ok = payload.get("engine_version") in {None, SHARP_TARGET_VERSION}
        return 0 if status in {"healthy", "disabled", "degraded"} and version_ok and age <= 120 else 1
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--healthcheck", action="store_true")
    args = parser.parse_args()
    if args.healthcheck:
        return healthcheck()
    setup_logging()
    asyncio.run(DesignImageDerivativeWorker().run_forever())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
