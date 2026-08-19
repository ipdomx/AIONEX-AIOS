"""Phase 36F durable asynchronous video execution authority (no provider HTTP transport)."""
from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from aios.video_factory import VIDEO_PROVIDER_CAPABILITIES
from app.db.base import SessionLocal
from app.db.models import (
    AuditEvent,
    MediaAssetEdge,
    MediaAssetGraph,
    MediaAssetNode,
    VideoExecution,
    uuid_str,
)
from app.services.media_storage import MediaObjectStore, media_object_store
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]
_ALLOWED_OUTPUT_FORMATS = frozenset({"mp4"})
_CONTENT_TYPES = {"mp4": "video/mp4"}
_SUFFIXES = {"mp4": ".mp4"}
_PENDING_PROVIDER_STATES = frozenset({"queued", "in_progress"})
_ALLOWED_COST_BASES = frozenset(
    {"unknown", "official_provider_usage", "official_fixed_second", "official_fixed_video"}
)


class VideoExecutionError(RuntimeError):
    """Durable video execution contract cannot proceed safely."""


class VideoLeaseLost(VideoExecutionError):
    """A stale worker attempted to act on a reclaimed video execution."""


@dataclass(frozen=True, slots=True)
class VideoClaim:
    execution_id: str
    lease_token: str
    fencing_token: int
    mode: str
    provider_job_id: str | None = None


@dataclass(frozen=True, slots=True)
class VideoExecutionSpec:
    organization_id: str
    requested_by_id: str
    graph_id: str
    target_node_id: str
    scene_key: str
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
    output_format: str = "mp4"
    estimated_cost_usd: float = 0.0
    max_attempts: int = 3
    max_polls: int = 360


def _now() -> datetime:
    return datetime.now(UTC)


def _capability(provider: str, model: str, operation: str):
    for item in VIDEO_PROVIDER_CAPABILITIES:
        if item.provider == provider and item.model == model and operation in item.operations:
            return item
    raise VideoExecutionError("provider/model/operation is outside the governed video launch matrix")


_SENSITIVE_METADATA_FRAGMENTS = (
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "secret",
    "prompt",
    "b64",
    "base64",
    "signed_url",
    "presigned",
    "download_url",
)
_SENSITIVE_TOKEN_KEYS = frozenset(
    {"token", "api_token", "access_token", "refresh_token", "id_token", "auth_token"}
)


def _metadata_key_is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return (
        any(fragment in lowered for fragment in _SENSITIVE_METADATA_FRAGMENTS)
        or lowered in _SENSITIVE_TOKEN_KEYS
        or lowered.endswith("_token")
        or lowered.startswith("token_")
    )


def _safe_metadata(payload: dict[str, Any]) -> dict[str, Any]:
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


def _inspect_video_envelope(body: bytes, output_format: str) -> None:
    if not body:
        raise VideoExecutionError("video provider returned an empty video")
    if output_format == "mp4":
        if len(body) < 12 or body[4:8] != b"ftyp":
            raise VideoExecutionError("video provider returned an invalid MP4 envelope")
        return
    raise VideoExecutionError("video output format is unsupported")


def _validate_spec(spec: VideoExecutionSpec) -> None:
    capability = _capability(spec.provider, spec.model, spec.operation)
    if spec.output_format not in _ALLOWED_OUTPUT_FORMATS:
        raise VideoExecutionError("video output format is unsupported")
    if not 1 <= spec.max_attempts <= 5:
        raise VideoExecutionError("video submission retry limit is outside the allowed range")
    if not 1 <= spec.max_polls <= 2_000:
        raise VideoExecutionError("video polling limit is outside the allowed range")
    if not 1 <= len(spec.prompt.strip()) <= 12_000:
        raise VideoExecutionError("compiled video prompt is outside the allowed range")
    if not 8 <= len(spec.idempotency_key.strip()) <= 160:
        raise VideoExecutionError("video idempotency key is invalid")
    if not 1 <= len(spec.scene_key.strip()) <= 80:
        raise VideoExecutionError("video scene key is invalid")
    if spec.estimated_cost_usd < 0 or spec.estimated_cost_usd > 1_000:
        raise VideoExecutionError("video estimated cost is outside the allowed range")
    options = dict(spec.request_options or {})
    duration = int(options.get("seconds") or options.get("duration_seconds") or 0)
    if duration and duration not in capability.durations_seconds:
        raise VideoExecutionError("video duration is unsupported by provider model")
    resolution = str(options.get("resolution") or "").strip().lower()
    if resolution and resolution not in capability.resolutions:
        raise VideoExecutionError("video resolution is unsupported by provider model")
    reference_count = int(options.get("reference_count") or 0)
    if reference_count < 0 or reference_count > capability.max_reference_images:
        raise VideoExecutionError("video reference count exceeds provider model capability")


async def create_video_execution(
    session: AsyncSession, *, spec: VideoExecutionSpec
) -> VideoExecution:
    """Create a planned video execution only. Provider spend requires explicit arm."""
    _validate_spec(spec)
    key = spec.idempotency_key.strip()
    existing = await session.scalar(
        select(VideoExecution).where(
            VideoExecution.organization_id == spec.organization_id,
            VideoExecution.idempotency_key == key,
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
        raise VideoExecutionError("video graph target is unavailable")
    if target.status != "planned" or target.storage_key or target.checksum:
        raise VideoExecutionError("video target is not a fresh planned node")
    if target.node_type not in {"provider-video", "video-provider-scene"}:
        raise VideoExecutionError("video target node type is unsupported")
    prompt = spec.prompt.strip()
    prompt_sha = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    target.prompt_metadata = {
        **(target.prompt_metadata or {}),
        "video_execution": {
            "provider": spec.provider,
            "model": spec.model,
            "operation": spec.operation,
            "scene_key": spec.scene_key,
            "compiled_prompt": prompt,
            "prompt_sha256": prompt_sha,
        },
    }
    target.operation_metadata = {
        **(target.operation_metadata or {}),
        "executor": "video-provider",
        "provider_operation": spec.operation,
        "output_format": spec.output_format,
        "request_options": dict(spec.request_options),
    }
    row = VideoExecution(
        id=uuid_str(),
        organization_id=spec.organization_id,
        workspace_id=spec.workspace_id,
        project_id=spec.project_id,
        studio_job_id=spec.studio_job_id,
        studio_asset_id=spec.studio_asset_id,
        graph_id=spec.graph_id,
        target_node_id=spec.target_node_id,
        requested_by_id=spec.requested_by_id,
        scene_key=spec.scene_key.strip(),
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
        poll_count=0,
        max_polls=spec.max_polls,
        fencing_token=0,
        provider_state="not_started",
        provider_response_metadata={},
        usage_metadata={},
        estimated_cost_usd=float(spec.estimated_cost_usd),
        actual_cost_usd=None,
        cost_basis="unknown",
    )
    session.add(row)
    await session.flush()
    return row


async def arm_video_execution(
    session: AsyncSession, *, execution_id: str, organization_id: str
) -> VideoExecution:
    row = await session.scalar(
        select(VideoExecution)
        .where(
            VideoExecution.id == execution_id,
            VideoExecution.organization_id == organization_id,
        )
        .with_for_update()
    )
    if row is None:
        raise VideoExecutionError("video execution not found")
    if row.status == "queued":
        return row
    if row.status != "planned":
        raise VideoExecutionError("only planned video executions may be armed")
    row.status = "queued"
    row.armed_at = _now()
    row.available_at = None
    row.error_code = None
    row.error_message = None
    await session.flush()
    return row


class VideoExecutionAuthority:
    def __init__(
        self,
        *,
        session_factory: SessionFactory = SessionLocal,
        store: MediaObjectStore | None = None,
        worker_id: str = "video-provider-worker",
        lease_seconds: int = 300,
    ) -> None:
        if not 30 <= lease_seconds <= 3_600:
            raise ValueError("video lease duration is outside the allowed range")
        self.session_factory = session_factory
        self.store = store or media_object_store()
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds

    async def reap_exhausted(self) -> int:
        now = _now()
        async with self.session_factory() as session:
            submission_exhausted = and_(
                VideoExecution.provider_job_id.is_(None),
                VideoExecution.provider_state != "submitting",
                VideoExecution.attempts >= VideoExecution.max_attempts,
            )
            polling_exhausted = and_(
                or_(
                    VideoExecution.provider_job_id.is_not(None),
                    VideoExecution.provider_state == "submitting",
                ),
                VideoExecution.poll_count >= VideoExecution.max_polls,
            )
            rows = list(
                (
                    await session.scalars(
                        select(VideoExecution)
                        .where(
                            VideoExecution.status.in_(("queued", "running")),
                            or_(submission_exhausted, polling_exhausted),
                            or_(
                                VideoExecution.status == "queued",
                                VideoExecution.lease_expires_at.is_(None),
                                VideoExecution.lease_expires_at <= now,
                            ),
                        )
                        .with_for_update(skip_locked=True)
                    )
                ).all()
            )
            for row in rows:
                row.status = "failed"
                row.error_code = (
                    "video_poll_exhausted" if row.provider_job_id else "video_submission_exhausted"
                )
                row.error_message = "Video execution exhausted its bounded retry/poll budget"
                row.lease_token = None
                row.lease_owner = None
                row.lease_expires_at = None
                row.available_at = None
                row.completed_at = now
                session.add(
                    AuditEvent(
                        organization_id=row.organization_id,
                        user_id=None,
                        action="video.provider.dead_lettered",
                        resource_type="video_execution",
                        resource_id=row.id,
                        details={
                            "scene_key": row.scene_key,
                            "provider": row.provider,
                            "model": row.model,
                            "provider_job_recorded": bool(row.provider_job_id),
                            "attempts": row.attempts,
                            "poll_count": row.poll_count,
                        },
                    )
                )
            if rows:
                await session.commit()
            return len(rows)

    async def claim(self) -> VideoClaim | None:
        await self.reap_exhausted()
        now = _now()
        parent_edge = aliased(MediaAssetEdge)
        parent_node = aliased(MediaAssetNode)
        async with self.session_factory() as session:
            blocked_parent = (
                select(parent_edge.id)
                .join(parent_node, parent_node.id == parent_edge.parent_node_id)
                .where(
                    parent_edge.child_node_id == VideoExecution.target_node_id,
                    parent_node.status != "completed",
                )
                .exists()
            )
            submission_budget = and_(
                VideoExecution.provider_job_id.is_(None),
                VideoExecution.provider_state != "submitting",
                VideoExecution.attempts < VideoExecution.max_attempts,
            )
            reconciliation_budget = and_(
                VideoExecution.provider_job_id.is_(None),
                VideoExecution.provider_state == "submitting",
                VideoExecution.poll_count < VideoExecution.max_polls,
            )
            poll_budget = and_(
                VideoExecution.provider_job_id.is_not(None),
                VideoExecution.poll_count < VideoExecution.max_polls,
            )
            ready = and_(
                VideoExecution.status == "queued",
                or_(VideoExecution.available_at.is_(None), VideoExecution.available_at <= now),
            )
            recovery = and_(
                VideoExecution.status == "running",
                VideoExecution.lease_expires_at.is_not(None),
                VideoExecution.lease_expires_at <= now,
            )
            row = await session.scalar(
                select(VideoExecution)
                .where(
                    or_(ready, recovery),
                    or_(submission_budget, reconciliation_budget, poll_budget),
                    ~blocked_parent,
                )
                .order_by(VideoExecution.created_at, VideoExecution.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if row is None:
                return None
            if row.provider_job_id:
                mode = "poll"
                row.poll_count = int(row.poll_count) + 1
                row.last_polled_at = now
            elif row.provider_state == "submitting":
                mode = "reconcile"
                row.poll_count = int(row.poll_count) + 1
                row.last_polled_at = now
            else:
                mode = "submit"
                row.attempts = int(row.attempts) + 1
            row.status = "running"
            row.fencing_token = int(row.fencing_token) + 1
            row.lease_token = str(uuid4())
            row.lease_owner = self.worker_id
            row.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
            row.available_at = None
            row.started_at = row.started_at or now
            row.error_code = None
            row.error_message = None
            await session.commit()
            return VideoClaim(
                row.id,
                str(row.lease_token),
                int(row.fencing_token),
                mode,
                row.provider_job_id,
            )

    async def mark_submission_started(self, claim: VideoClaim) -> None:
        if claim.mode != "submit":
            raise VideoExecutionError("only a submit claim may start provider submission")
        async with self.session_factory() as session:
            row = await session.scalar(
                select(VideoExecution)
                .where(VideoExecution.id == claim.execution_id)
                .with_for_update()
            )
            row = self._require_owned(row, claim)
            if row.provider_job_id:
                raise VideoExecutionError("video provider job is already recorded")
            if row.provider_state != "not_started":
                raise VideoExecutionError("video provider submission state is not fresh")
            row.provider_state = "submitting"
            row.provider_submitted_at = row.provider_submitted_at or _now()
            await session.commit()

    def _owns(self, row: VideoExecution | None, claim: VideoClaim) -> bool:
        return bool(
            row is not None
            and row.status == "running"
            and row.lease_owner == self.worker_id
            and row.lease_token == claim.lease_token
            and int(row.fencing_token) == claim.fencing_token
        )

    def _require_owned(self, row: VideoExecution | None, claim: VideoClaim) -> VideoExecution:
        if not self._owns(row, claim):
            raise VideoLeaseLost(claim.execution_id)
        assert row is not None
        return row

    async def renew(self, claim: VideoClaim) -> None:
        async with self.session_factory() as session:
            row = await session.scalar(
                select(VideoExecution)
                .where(VideoExecution.id == claim.execution_id)
                .with_for_update()
            )
            row = self._require_owned(row, claim)
            row.lease_expires_at = _now() + timedelta(seconds=self.lease_seconds)
            await session.commit()

    async def record_provider_job(
        self,
        claim: VideoClaim,
        *,
        provider_job_id: str,
        provider_state: str,
        provider_response_metadata: dict[str, Any],
        progress: int | None = None,
        poll_after_seconds: int = 5,
    ) -> None:
        if claim.mode not in {"submit", "reconcile"}:
            raise VideoExecutionError("provider job identity may be recorded only by submit/reconcile claims")
        job_id = provider_job_id.strip()
        if not 1 <= len(job_id) <= 240:
            raise VideoExecutionError("video provider job id is invalid")
        if provider_state not in _PENDING_PROVIDER_STATES:
            raise VideoExecutionError("video provider job state is not pending")
        if progress is not None and not 0 <= progress <= 99:
            raise VideoExecutionError("video provider progress is outside the pending range")
        async with self.session_factory() as session:
            row = await session.scalar(
                select(VideoExecution)
                .where(VideoExecution.id == claim.execution_id)
                .with_for_update()
            )
            row = self._require_owned(row, claim)
            if row.provider_job_id and row.provider_job_id != job_id:
                raise VideoExecutionError("video provider job identity cannot change")
            if not row.provider_job_id and row.provider_state != "submitting":
                raise VideoExecutionError("video provider submission was not durably marked before HTTP")
            row.provider_job_id = job_id
            row.provider_state = provider_state
            row.provider_progress = progress
            row.provider_submitted_at = row.provider_submitted_at or _now()
            row.provider_response_metadata = _safe_metadata(provider_response_metadata)
            self._requeue(row, poll_after_seconds=poll_after_seconds)
            await session.commit()

    async def record_poll_pending(
        self,
        claim: VideoClaim,
        *,
        provider_state: str,
        provider_response_metadata: dict[str, Any],
        progress: int | None = None,
        poll_after_seconds: int = 5,
    ) -> None:
        if claim.mode != "poll":
            raise VideoExecutionError("provider pending state may be recorded only by a poll claim")
        if provider_state not in _PENDING_PROVIDER_STATES:
            raise VideoExecutionError("video provider poll state is not pending")
        if progress is not None and not 0 <= progress <= 99:
            raise VideoExecutionError("video provider progress is outside the pending range")
        async with self.session_factory() as session:
            row = await session.scalar(
                select(VideoExecution)
                .where(VideoExecution.id == claim.execution_id)
                .with_for_update()
            )
            row = self._require_owned(row, claim)
            if not row.provider_job_id:
                raise VideoExecutionError("video provider job must be recorded before polling")
            row.provider_state = provider_state
            row.provider_progress = progress
            row.last_polled_at = _now()
            row.provider_response_metadata = {
                **(row.provider_response_metadata or {}),
                **_safe_metadata(provider_response_metadata),
            }
            self._requeue(row, poll_after_seconds=poll_after_seconds)
            await session.commit()

    def _requeue(self, row: VideoExecution, *, poll_after_seconds: int) -> None:
        delay = max(1, min(int(poll_after_seconds), 300))
        row.status = "queued"
        row.available_at = _now() + timedelta(seconds=delay)
        row.lease_token = None
        row.lease_owner = None
        row.lease_expires_at = None

    async def fail(
        self,
        claim: VideoClaim,
        *,
        code: str,
        message: str,
        permanent: bool = False,
        retry_after_seconds: int = 5,
        submission_safe_to_retry: bool = False,
    ) -> None:
        safe_code = code.strip()[:120] or "video_execution_failure"
        safe_message = message.strip()[:1000] or "Video provider execution failed"
        async with self.session_factory() as session:
            row = await session.scalar(
                select(VideoExecution)
                .where(VideoExecution.id == claim.execution_id)
                .with_for_update()
            )
            row = self._require_owned(row, claim)
            if submission_safe_to_retry:
                if claim.mode != "submit":
                    raise VideoExecutionError("only a submit claim may reopen a definitive submission retry")
                if row.provider_job_id or row.provider_state != "submitting":
                    raise VideoExecutionError(
                        "submission retry may be reopened only after a definitively rejected fresh submission"
                    )
                row.provider_state = "not_started"
            exhausted = permanent or (
                (not row.provider_job_id and row.provider_state != "submitting" and row.attempts >= row.max_attempts)
                or (
                    (bool(row.provider_job_id) or row.provider_state == "submitting")
                    and row.poll_count >= row.max_polls
                )
            )
            row.error_code = safe_code
            row.error_message = safe_message
            if exhausted:
                row.status = "failed"
                row.provider_state = "failed" if row.provider_job_id else row.provider_state
                row.completed_at = _now()
                row.available_at = None
            else:
                row.status = "queued"
                row.available_at = _now() + timedelta(
                    seconds=max(1, min(int(retry_after_seconds), 300))
                )
            row.lease_token = None
            row.lease_owner = None
            row.lease_expires_at = None
            await session.commit()

    async def complete_bytes(
        self,
        claim: VideoClaim,
        *,
        body: bytes,
        content_type: str,
        provider_response_metadata: dict[str, Any],
        usage_metadata: dict[str, Any],
        actual_cost_usd: float | None,
        cost_basis: str = "unknown",
    ) -> dict[str, Any]:
        if claim.mode != "poll":
            raise VideoExecutionError("video completion requires a poll claim")
        if actual_cost_usd is not None and (actual_cost_usd < 0 or actual_cost_usd > 1_000):
            raise VideoExecutionError("video actual cost is outside the allowed range")
        safe_cost_basis = cost_basis.strip()[:64] or "unknown"
        if safe_cost_basis not in _ALLOWED_COST_BASES:
            raise VideoExecutionError("video cost basis is unsupported")
        async with self.session_factory() as session:
            row = await session.get(VideoExecution, claim.execution_id)
            row = self._require_owned(row, claim)
            if not row.provider_job_id:
                raise VideoExecutionError("video provider job is missing at completion")
            output_format = row.output_format
            if _CONTENT_TYPES[output_format] != content_type:
                raise VideoExecutionError("video content type does not match the governed output format")
            _inspect_video_envelope(body, output_format)
            key = (
                f"media/{row.organization_id}/video/{row.graph_id}/{row.target_node_id}/"
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
                provider_response_metadata=_safe_metadata(provider_response_metadata),
                usage_metadata=_safe_metadata(usage_metadata),
                actual_cost_usd=actual_cost_usd,
                cost_basis=safe_cost_basis,
            )
        except Exception:
            await asyncio.to_thread(self.store.delete, stored.key)
            raise

    async def _complete_stored(
        self,
        claim: VideoClaim,
        *,
        storage_backend: str,
        storage_key: str,
        checksum: str,
        size_bytes: int,
        content_type: str,
        provider_response_metadata: dict[str, Any],
        usage_metadata: dict[str, Any],
        actual_cost_usd: float | None,
        cost_basis: str,
    ) -> dict[str, Any]:
        async with self.session_factory() as session:
            row = await session.scalar(
                select(VideoExecution)
                .where(VideoExecution.id == claim.execution_id)
                .with_for_update()
            )
            row = self._require_owned(row, claim)
            graph = await session.scalar(
                select(MediaAssetGraph).where(MediaAssetGraph.id == row.graph_id).with_for_update()
            )
            target = await session.scalar(
                select(MediaAssetNode).where(MediaAssetNode.id == row.target_node_id).with_for_update()
            )
            if graph is None or target is None:
                raise VideoExecutionError("video graph target disappeared during completion")
            if target.status != "planned" or target.storage_key or target.checksum:
                raise VideoExecutionError("video graph target changed before completion")
            target.status = "completed"
            target.storage_backend = storage_backend
            target.storage_key = storage_key
            target.checksum = checksum
            target.size_bytes = size_bytes
            target.media_type = content_type
            target.source_metadata = {
                **(target.source_metadata or {}),
                "content_type": content_type,
                "provider": row.provider,
                "model": row.model,
                "provider_job_id": row.provider_job_id,
                "provider_state": "completed",
            }
            target.provenance = [
                *(target.provenance or []),
                {
                    "type": "provider-video-output",
                    "provider": row.provider,
                    "model": row.model,
                    "execution_id": row.id,
                    "checksum": checksum,
                },
            ]
            row.status = "completed"
            row.provider_state = "completed"
            row.provider_progress = 100
            row.provider_response_metadata = {
                **(row.provider_response_metadata or {}),
                **provider_response_metadata,
            }
            row.usage_metadata = usage_metadata
            row.actual_cost_usd = actual_cost_usd
            row.cost_basis = cost_basis
            row.output_storage_backend = storage_backend
            row.output_storage_key = storage_key
            row.output_checksum = checksum
            row.output_size_bytes = size_bytes
            row.error_code = None
            row.error_message = None
            row.lease_token = None
            row.lease_owner = None
            row.lease_expires_at = None
            row.available_at = None
            row.completed_at = _now()
            await session.flush()
            pending = int(
                await session.scalar(
                    select(func.count(MediaAssetNode.id)).where(
                        MediaAssetNode.graph_id == row.graph_id,
                        MediaAssetNode.status != "completed",
                    )
                )
                or 0
            )
            graph.status = "completed" if pending == 0 else "rendering"
            session.add(
                AuditEvent(
                    organization_id=row.organization_id,
                    user_id=row.requested_by_id,
                    action="video.provider.completed",
                    resource_type="video_execution",
                    resource_id=row.id,
                    details={
                        "scene_key": row.scene_key,
                        "provider": row.provider,
                        "model": row.model,
                        "provider_job_id": row.provider_job_id,
                        "checksum": checksum,
                        "size_bytes": size_bytes,
                        "cost_basis": cost_basis,
                        "actual_cost_usd": actual_cost_usd,
                        "graph_pending_nodes": pending,
                    },
                )
            )
            await session.commit()
            return {
                "execution_id": row.id,
                "graph_id": row.graph_id,
                "target_node_id": row.target_node_id,
                "scene_key": row.scene_key,
                "checksum": checksum,
                "size_bytes": size_bytes,
                "storage_backend": storage_backend,
                "provider_job_id": row.provider_job_id,
                "graph_pending_nodes": pending,
            }
