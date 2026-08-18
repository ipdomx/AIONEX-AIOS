"""Phase 36E durable provider-image execution authority (no provider HTTP transport)."""
from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from aios.design_factory import IMAGE_PROVIDER_CAPABILITIES
from app.db.base import SessionLocal
from app.db.models import (
    AuditEvent,
    DesignImageExecution,
    MediaAssetEdge,
    MediaAssetGraph,
    MediaAssetNode,
    StudioAsset,
    StudioAssetRevision,
    uuid_str,
)
from app.services.media_storage import MediaObjectStore, media_object_store
from app.services.image_raster_validation import ImageRasterValidationError, inspect_raster
from app.services.production_studio import slug
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]
_ALLOWED_OUTPUT_FORMATS = frozenset({"png", "jpeg", "webp"})
_CONTENT_TYPES = {"png": "image/png", "jpeg": "image/jpeg", "webp": "image/webp"}
_SUFFIXES = {"png": ".png", "jpeg": ".jpg", "webp": ".webp"}
_ALLOWED_COST_BASES = frozenset({"unknown", "official_provider_usage", "official_fixed_step", "official_fixed_image"})


class DesignImageExecutionError(RuntimeError):
    """Durable image execution contract cannot proceed safely."""


class DesignImageLeaseLost(DesignImageExecutionError):
    """A stale worker attempted to act on a reclaimed image execution."""


@dataclass(frozen=True, slots=True)
class DesignImageClaim:
    execution_id: str
    lease_token: str
    fencing_token: int


@dataclass(frozen=True, slots=True)
class DesignImageExecutionSpec:
    organization_id: str
    requested_by_id: str
    graph_id: str
    target_node_id: str
    provider: str
    model: str
    operation: str
    prompt: str
    idempotency_key: str
    request_options: dict[str, Any]
    workspace_id: str | None = None
    project_id: str | None = None
    studio_job_id: str | None = None
    studio_asset_id: str | None = None
    output_format: str = "png"
    estimated_cost_usd: float = 0.0
    max_attempts: int = 3


def _now() -> datetime:
    return datetime.now(UTC)


def _inspect_raster(body: bytes, output_format: str) -> tuple[int, int]:
    """Compatibility wrapper that preserves DesignImageExecutionError semantics."""
    try:
        return inspect_raster(body, output_format)
    except ImageRasterValidationError as exc:
        raise DesignImageExecutionError(str(exc)) from exc


def _capability(provider: str, model: str, operation: str):
    for item in IMAGE_PROVIDER_CAPABILITIES:
        if item.provider == provider and item.model == model and operation in item.operations:
            return item
    raise DesignImageExecutionError("provider/model/operation is outside the governed image launch matrix")


_SENSITIVE_METADATA_FRAGMENTS = (
    "api_key", "apikey", "authorization", "credential", "secret",
    "prompt", "b64", "base64", "image_data", "signed_url", "presigned",
)
_SENSITIVE_TOKEN_KEYS = frozenset({
    "token", "api_token", "access_token", "refresh_token", "id_token",
    "auth_token", "bearer_token", "session_token", "credential_token",
})


def _metadata_key_is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return (
        any(fragment in lowered for fragment in _SENSITIVE_METADATA_FRAGMENTS)
        or lowered in _SENSITIVE_TOKEN_KEYS
        or lowered.endswith("_token")
        or lowered.startswith("token_")
    )


def _safe_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    """Retain bounded operational evidence while dropping secret/content-bearing fields."""
    result: dict[str, Any] = {}
    for raw_key, raw_value in list(payload.items())[:64]:
        key = str(raw_key)[:120]
        if _metadata_key_is_sensitive(key):
            continue
        if raw_value is None or isinstance(raw_value, (bool, int, float)):
            result[key] = raw_value
        elif isinstance(raw_value, str):
            result[key] = raw_value[:500]
        elif isinstance(raw_value, dict):
            result[key] = _safe_metadata(raw_value)
        elif isinstance(raw_value, list):
            safe_items: list[Any] = []
            for item in raw_value[:32]:
                if item is None or isinstance(item, (bool, int, float)):
                    safe_items.append(item)
                elif isinstance(item, str):
                    safe_items.append(item[:500])
                elif isinstance(item, dict):
                    safe_items.append(_safe_metadata(item))
            result[key] = safe_items
    return result


def _validate_spec(spec: DesignImageExecutionSpec) -> None:
    capability = _capability(spec.provider, spec.model, spec.operation)
    if spec.output_format not in _ALLOWED_OUTPUT_FORMATS:
        raise DesignImageExecutionError("design image output format is unsupported")
    if spec.output_format not in capability.output_formats:
        raise DesignImageExecutionError("design image output format is unsupported by provider model")
    if not 1 <= spec.max_attempts <= 5:
        raise DesignImageExecutionError("design image retry limit is outside the allowed range")
    if not 1 <= len(spec.prompt.strip()) <= 12_000:
        raise DesignImageExecutionError("compiled design prompt is outside the allowed range")
    if not 8 <= len(spec.idempotency_key.strip()) <= 160:
        raise DesignImageExecutionError("design image idempotency key is invalid")
    if spec.estimated_cost_usd < 0 or spec.estimated_cost_usd > 100:
        raise DesignImageExecutionError("design image estimated cost is outside the allowed range")


async def create_design_image_execution(
    session: AsyncSession,
    *,
    spec: DesignImageExecutionSpec,
) -> DesignImageExecution:
    """Create a planned execution only. It cannot spend until explicitly armed."""
    _validate_spec(spec)
    key = spec.idempotency_key.strip()
    existing = await session.scalar(
        select(DesignImageExecution).where(
            DesignImageExecution.organization_id == spec.organization_id,
            DesignImageExecution.idempotency_key == key,
        )
    )
    if existing is not None:
        return existing
    graph = await session.scalar(
        select(MediaAssetGraph).where(
            MediaAssetGraph.id == spec.graph_id,
            MediaAssetGraph.organization_id == spec.organization_id,
        )
    )
    target = await session.scalar(
        select(MediaAssetNode).where(
            MediaAssetNode.id == spec.target_node_id,
            MediaAssetNode.graph_id == spec.graph_id,
            MediaAssetNode.organization_id == spec.organization_id,
        )
    )
    if graph is None or target is None:
        raise DesignImageExecutionError("design image graph target is unavailable")
    if target.status != "planned" or target.storage_key or target.checksum:
        raise DesignImageExecutionError("design image target is not a fresh planned node")
    if target.node_type not in {"provider-image", "image"}:
        raise DesignImageExecutionError("design image target node type is unsupported")
    prompt = spec.prompt.strip()
    prompt_sha = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    target.prompt_metadata = {
        **(target.prompt_metadata or {}),
        "design_image": {
            "provider": spec.provider,
            "model": spec.model,
            "operation": spec.operation,
            "compiled_prompt": prompt,
            "prompt_sha256": prompt_sha,
        },
    }
    target.operation_metadata = {
        **(target.operation_metadata or {}),
        "executor": "design-image-provider",
        "provider_operation": spec.operation,
        "output_format": spec.output_format,
        "request_options": dict(spec.request_options),
    }
    row = DesignImageExecution(
        id=uuid_str(),
        organization_id=spec.organization_id,
        workspace_id=spec.workspace_id,
        project_id=spec.project_id,
        studio_job_id=spec.studio_job_id,
        studio_asset_id=spec.studio_asset_id,
        graph_id=spec.graph_id,
        target_node_id=spec.target_node_id,
        requested_by_id=spec.requested_by_id,
        operation=spec.operation,
        provider=spec.provider,
        model=spec.model,
        status="planned",
        idempotency_key=key,
        prompt_sha256=prompt_sha,
        request_options=dict(spec.request_options),
        output_format=spec.output_format,
        attempts=0,
        max_attempts=spec.max_attempts,
        fencing_token=0,
        provider_response_metadata={},
        usage_metadata={},
        estimated_cost_usd=float(spec.estimated_cost_usd),
        actual_cost_usd=None,
        cost_basis="unknown",
    )
    session.add(row)
    await session.flush()
    return row


async def arm_design_image_execution(
    session: AsyncSession, *, execution_id: str, organization_id: str
) -> DesignImageExecution:
    row = await session.scalar(
        select(DesignImageExecution)
        .where(
            DesignImageExecution.id == execution_id,
            DesignImageExecution.organization_id == organization_id,
        )
        .with_for_update()
    )
    if row is None:
        raise DesignImageExecutionError("design image execution not found")
    if row.status == "queued":
        return row
    if row.status != "planned":
        raise DesignImageExecutionError("only planned design image executions may be armed")
    row.status = "queued"
    row.armed_at = _now()
    row.available_at = None
    row.error_code = None
    row.error_message = None
    await session.flush()
    return row


class DesignImageExecutionAuthority:
    def __init__(
        self,
        *,
        session_factory: SessionFactory = SessionLocal,
        store: MediaObjectStore | None = None,
        worker_id: str = "design-image-worker",
        lease_seconds: int = 300,
    ) -> None:
        if not 30 <= lease_seconds <= 3600:
            raise ValueError("design image lease duration is outside the allowed range")
        self.session_factory = session_factory
        self.store = store or media_object_store()
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds

    async def claim(self) -> DesignImageClaim | None:
        now = _now()
        parent_edge = aliased(MediaAssetEdge)
        parent_node = aliased(MediaAssetNode)
        async with self.session_factory() as session:
            blocked_parent = (
                select(parent_edge.id)
                .join(parent_node, parent_node.id == parent_edge.parent_node_id)
                .where(
                    parent_edge.child_node_id == DesignImageExecution.target_node_id,
                    parent_node.status != "completed",
                )
                .exists()
            )
            row = await session.scalar(
                select(DesignImageExecution)
                .where(
                    DesignImageExecution.attempts < DesignImageExecution.max_attempts,
                    or_(
                        and_(
                            DesignImageExecution.status == "queued",
                            or_(
                                DesignImageExecution.available_at.is_(None),
                                DesignImageExecution.available_at <= now,
                            ),
                        ),
                        and_(
                            DesignImageExecution.status == "running",
                            DesignImageExecution.lease_expires_at.is_not(None),
                            DesignImageExecution.lease_expires_at <= now,
                        ),
                    ),
                    ~blocked_parent,
                )
                .order_by(DesignImageExecution.created_at, DesignImageExecution.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if row is None:
                return None
            row.status = "running"
            row.attempts = int(row.attempts) + 1
            row.fencing_token = int(row.fencing_token) + 1
            row.lease_token = str(uuid4())
            row.lease_owner = self.worker_id
            row.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
            row.available_at = None
            row.started_at = row.started_at or now
            row.error_code = None
            row.error_message = None
            await session.commit()
            return DesignImageClaim(row.id, str(row.lease_token), int(row.fencing_token))

    async def renew(self, claim: DesignImageClaim) -> None:
        async with self.session_factory() as session:
            row = await session.scalar(
                select(DesignImageExecution)
                .where(DesignImageExecution.id == claim.execution_id)
                .with_for_update()
            )
            row = self._require_owned(row, claim)
            row.lease_expires_at = _now() + timedelta(seconds=self.lease_seconds)
            await session.commit()

    def _owns(self, row: DesignImageExecution | None, claim: DesignImageClaim) -> bool:
        return bool(
            row is not None
            and row.status == "running"
            and row.lease_owner == self.worker_id
            and row.lease_token == claim.lease_token
            and int(row.fencing_token) == claim.fencing_token
        )

    def _require_owned(
        self, row: DesignImageExecution | None, claim: DesignImageClaim
    ) -> DesignImageExecution:
        if not self._owns(row, claim):
            raise DesignImageLeaseLost(claim.execution_id)
        assert row is not None
        return row

    async def fail(
        self, claim: DesignImageClaim, *, code: str, message: str, permanent: bool = False
    ) -> None:
        safe_code = code.strip()[:120] or "design_image_failure"
        safe_message = message.strip()[:1000] or "Design image execution failed"
        async with self.session_factory() as session:
            row = await session.scalar(
                select(DesignImageExecution)
                .where(DesignImageExecution.id == claim.execution_id)
                .with_for_update()
            )
            row = self._require_owned(row, claim)
            exhausted = permanent or int(row.attempts) >= int(row.max_attempts)
            if permanent:
                row.attempts = row.max_attempts
            row.status = "failed" if exhausted else "queued"
            row.error_code = safe_code
            row.error_message = safe_message
            row.lease_token = None
            row.lease_owner = None
            row.lease_expires_at = None
            row.available_at = None if exhausted else _now() + timedelta(seconds=min(300, 2 ** row.attempts))
            if exhausted:
                row.completed_at = _now()
            await session.commit()

    async def complete_bytes(
        self,
        claim: DesignImageClaim,
        *,
        body: bytes,
        content_type: str,
        provider_request_id: str | None,
        provider_response_metadata: dict[str, Any],
        usage_metadata: dict[str, Any],
        actual_cost_usd: float | None,
        cost_basis: str = "unknown",
    ) -> dict[str, Any]:
        if not body:
            raise DesignImageExecutionError("design image provider returned an empty image")
        if actual_cost_usd is not None and (actual_cost_usd < 0 or actual_cost_usd > 100):
            raise DesignImageExecutionError("design image actual cost is outside the allowed range")
        safe_cost_basis = cost_basis.strip()[:64] or "unknown"
        if safe_cost_basis not in _ALLOWED_COST_BASES:
            raise DesignImageExecutionError("design image cost basis is unsupported")
        async with self.session_factory() as session:
            row = await session.get(DesignImageExecution, claim.execution_id)
            row = self._require_owned(row, claim)
            output_format = row.output_format
            if _CONTENT_TYPES[output_format] != content_type:
                raise DesignImageExecutionError("design image content type does not match the governed output format")
            width, height = _inspect_raster(body, output_format)
            key = (
                f"media/{row.organization_id}/design/{row.graph_id}/{row.target_node_id}/"
                f"f{claim.fencing_token}{_SUFFIXES[output_format]}"
            )
        stored = await asyncio.to_thread(
            self.store.put_bytes,
            key,
            body,
            content_type,
            metadata={"execution-id": claim.execution_id, "fencing-token": str(claim.fencing_token)},
        )
        try:
            return await self._complete_stored(
                claim,
                storage_backend=stored.backend,
                storage_key=stored.key,
                checksum=stored.sha256,
                size_bytes=stored.size_bytes,
                content_type=content_type,
                provider_request_id=provider_request_id,
                provider_response_metadata=_safe_metadata(
                    {**provider_response_metadata, "width": width, "height": height}
                ),
                usage_metadata=_safe_metadata(usage_metadata),
                actual_cost_usd=actual_cost_usd,
                cost_basis=safe_cost_basis,
            )
        except Exception:
            await asyncio.to_thread(self.store.delete, stored.key)
            raise

    async def _complete_stored(
        self,
        claim: DesignImageClaim,
        *,
        storage_backend: str,
        storage_key: str,
        checksum: str,
        size_bytes: int,
        content_type: str,
        provider_request_id: str | None,
        provider_response_metadata: dict[str, Any],
        usage_metadata: dict[str, Any],
        actual_cost_usd: float | None,
        cost_basis: str,
    ) -> dict[str, Any]:
        completed = _now()
        async with self.session_factory() as session:
            row = await session.scalar(
                select(DesignImageExecution)
                .where(DesignImageExecution.id == claim.execution_id)
                .with_for_update()
            )
            row = self._require_owned(row, claim)
            target = await session.scalar(
                select(MediaAssetNode)
                .where(
                    MediaAssetNode.id == row.target_node_id,
                    MediaAssetNode.graph_id == row.graph_id,
                    MediaAssetNode.organization_id == row.organization_id,
                )
                .with_for_update()
            )
            graph = await session.scalar(
                select(MediaAssetGraph)
                .where(
                    MediaAssetGraph.id == row.graph_id,
                    MediaAssetGraph.organization_id == row.organization_id,
                )
                .with_for_update()
            )
            if target is None or graph is None:
                raise DesignImageExecutionError("design image graph target disappeared")
            target.status = "completed"
            target.storage_backend = storage_backend
            target.storage_key = storage_key
            target.checksum = checksum
            target.size_bytes = size_bytes
            target.media_type = content_type
            target.provenance = [
                *(target.provenance or []),
                {
                    "type": "provider-image",
                    "provider": row.provider,
                    "model": row.model,
                    "operation": row.operation,
                    "provider_request_id": provider_request_id,
                    "prompt_sha256": row.prompt_sha256,
                    "output_checksum": checksum,
                    "fencing_token": claim.fencing_token,
                    "completed_at": completed.isoformat(),
                },
            ]
            row.status = "completed"
            row.provider_request_id = provider_request_id
            row.provider_response_metadata = dict(provider_response_metadata)
            row.usage_metadata = dict(usage_metadata)
            row.actual_cost_usd = float(actual_cost_usd) if actual_cost_usd is not None else None
            row.cost_basis = cost_basis
            row.output_storage_backend = storage_backend
            row.output_storage_key = storage_key
            row.output_checksum = checksum
            row.output_size_bytes = size_bytes
            row.completed_at = completed
            row.lease_token = None
            row.lease_owner = None
            row.lease_expires_at = None
            row.available_at = None
            row.error_code = None
            row.error_message = None
            incomplete_nodes = int(
                await session.scalar(
                    select(func.count(MediaAssetNode.id)).where(
                        MediaAssetNode.graph_id == graph.id,
                        MediaAssetNode.status != "completed",
                    )
                )
                or 0
            )
            completion: dict[str, Any] = {}
            if incomplete_nodes == 0:
                graph.status = "completed"
                completion = {
                    "completed_at": completed.isoformat(),
                    "final_node_id": target.id,
                    "final_checksum": checksum,
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
                        raise DesignImageExecutionError("design image Studio asset is unavailable")
                    revision_number = int(asset.current_revision) + 1
                    suffix = _SUFFIXES[row.output_format]
                    filename = f"{slug(graph.title)}-design-v{graph.graph_version}{suffix}"
                    output_metadata = {
                        "graph_id": graph.id,
                        "graph_version": graph.graph_version,
                        "execution_id": row.id,
                        "storage_backend": storage_backend,
                        "storage_key": storage_key,
                        "provider": row.provider,
                        "model": row.model,
                        "operation": row.operation,
                        "prompt_sha256": row.prompt_sha256,
                        "usage": dict(usage_metadata),
                        "actual_cost_usd": float(actual_cost_usd) if actual_cost_usd is not None else None,
                        "cost_basis": cost_basis,
                    }
                    revision = StudioAssetRevision(
                        id=uuid_str(),
                        organization_id=graph.organization_id,
                        asset_id=asset.id,
                        job_id=graph.studio_job_id or asset.job_id,
                        created_by_id=graph.created_by_id,
                        revision_number=revision_number,
                        filename=filename,
                        media_type=content_type,
                        storage_path=storage_key,
                        checksum=checksum,
                        size_bytes=size_bytes,
                        change_note=f"Phase 36E provider image graph v{graph.graph_version}",
                        revision_metadata={"design_image_output": output_metadata},
                        status="active",
                    )
                    session.add(revision)
                    asset.current_revision = revision_number
                    asset.filename = filename
                    asset.media_type = content_type
                    asset.storage_path = storage_key
                    asset.checksum = checksum
                    asset.size_bytes = size_bytes
                    asset.asset_metadata = {
                        **(asset.asset_metadata or {}),
                        "design_image_output": output_metadata,
                    }
                    completion.update(
                        {
                            "studio_asset_id": asset.id,
                            "studio_revision_id": revision.id,
                            "studio_revision_number": revision_number,
                        }
                    )
                graph.graph_metadata = {**(graph.graph_metadata or {}), **completion}
            session.add(
                AuditEvent(
                    organization_id=row.organization_id,
                    user_id=None,
                    action="design.image.completed",
                    resource_type="design_image_execution",
                    resource_id=row.id,
                    details={
                        "graph_id": row.graph_id,
                        "target_node_id": row.target_node_id,
                        "provider": row.provider,
                        "model": row.model,
                        "operation": row.operation,
                        "output_checksum": checksum,
                        "fencing_token": claim.fencing_token,
                    },
                )
            )
            await session.commit()
            return {
                "execution_id": row.id,
                "graph_id": row.graph_id,
                "target_node_id": row.target_node_id,
                "status": row.status,
                "output_checksum": checksum,
                "storage_backend": storage_backend,
                **completion,
            }
