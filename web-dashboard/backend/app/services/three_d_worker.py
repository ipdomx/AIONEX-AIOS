"""Durable RunPod-backed 3D generation worker for Phase 34D."""

from __future__ import annotations

import argparse
import asyncio
import base64
from datetime import datetime, timedelta
from hashlib import sha256
import json
import os
from pathlib import Path
import signal
import time
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import and_, or_, select
from sqlalchemy.sql.elements import ColumnElement

from aios.gpu_worker.runpod import RunPodError, RunPodServerlessClient
from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.db.base import SessionLocal
from app.db.models import ThreeDArtifact, ThreeDGenerationJob, uuid_str
from app.services import billing, communications
from app.services.three_d_policy import get_three_d_policy
from app.services.three_d_provider_policy import provider_runtime_configured
from app.services.three_d_resilience import (
    cleanup_expired_three_d_data,
    assert_provider_available,
    maybe_emit_spend_alerts,
    provider_circuit_snapshot,
    provider_outage_alert,
    record_provider_failure,
    record_provider_success,
)
from app.services.three_d_product import (
    audit_job,
    now,
    notify_job,
    provider_error_requires_clarification,
)
from app.services.three_d_storage import (
    GLB_MEDIA_TYPE,
    ThreeDObjectStore,
    ThreeDStorageError,
)

logger = get_logger(__name__)


class ThreeDWorkerError(RuntimeError):
    """Sanitized durable 3D worker failure."""


def _env_file(path: str) -> dict[str, str]:
    source = Path(path)
    if not source.is_file() or source.is_symlink():
        raise ThreeDWorkerError("3D provider credentials are unavailable")
    values: dict[str, str] = {}
    for raw in source.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _runpod_clients() -> dict[str, RunPodServerlessClient]:
    values = _env_file(settings.THREE_D_RUNPOD_SECRET_FILE)
    key = values.get("RUNPOD_API_KEY", "").strip()
    primary_endpoint = values.get("RUNPOD_ENDPOINT_ID", "").strip()
    fallback_endpoint = values.get("RUNPOD_FALLBACK_ENDPOINT_ID", "").strip()
    if not key:
        raise ThreeDWorkerError("3D provider credentials are incomplete")
    clients: dict[str, RunPodServerlessClient] = {}
    if primary_endpoint:
        primary = RunPodServerlessClient(key, primary_endpoint)
        clients.update({"hunyuan3d": primary, "runpod": primary})
    if fallback_endpoint:
        clients["triposr"] = RunPodServerlessClient(key, fallback_endpoint)
    if not clients:
        raise ThreeDWorkerError("No 3D provider endpoint is configured")
    return clients


def _safe_provider_message(state: str) -> str:
    if state == "TIMED_OUT":
        return "3D generation exceeded the Owner-defined runtime limit."
    if state == "CANCELLED":
        return "3D generation was cancelled before completion."
    return "The 3D provider could not complete this request."


def _manifest_acceptable(provider: str, manifest: dict) -> bool:
    key = provider.strip().lower()
    if key in {"runpod", "hunyuan3d"}:
        return (
            manifest.get("fallback_used") is False
            and int(manifest.get("pbr_material_count") or 0) >= 1
            and int(manifest.get("texture_count") or 0) >= 1
        )
    if key == "triposr":
        return (
            manifest.get("fallback_used") is True
            and manifest.get("fallback_provider") == "triposr"
            and str(manifest.get("license") or "").upper() == "MIT"
            and int(manifest.get("mesh_count") or 0) >= 1
            and int(manifest.get("material_count") or 0) >= 1
            and int(manifest.get("texture_count") or 0) >= 1
        )
    return False


class ThreeDGenerationWorker:
    def __init__(self) -> None:
        self.stop_event = asyncio.Event()
        self.health_path = Path(settings.THREE_D_WORKER_HEALTH_FILE)
        self.cycles = 0
        self.errors = 0
        self.runpods = _runpod_clients()
        self.runpod = self.runpods.get("hunyuan3d")  # backward-compatible primary alias
        self.storage = ThreeDObjectStore()
        self.next_cleanup_at = 0.0
        self.circuit_state = "unknown"
        self.last_cleanup_at: str | None = None
        self.last_provider_success_at: str | None = None
        self.last_provider_failure_at: str | None = None

    def _client_for_provider(self, provider: str) -> RunPodServerlessClient:
        key = provider.strip().lower()
        if key == "runpod":
            key = "hunyuan3d"
        client = self.runpods.get(key)
        if client is None:
            raise ThreeDWorkerError(f"3D provider endpoint is not configured: {key}")
        return client

    @property
    def stale_before(self) -> datetime:
        return now() - timedelta(seconds=settings.THREE_D_JOB_LEASE_SECONDS)

    def write_health(self, status: str) -> None:
        payload = {
            "status": status,
            "checked_at": now().isoformat(),
            "checked_at_epoch": time.time(),
            "cycles": self.cycles,
            "errors": self.errors,
            "provider_secret_returned": False,
            "object_storage_private": True,
            "circuit_state": self.circuit_state,
            "last_cleanup_at": self.last_cleanup_at,
            "last_provider_success_at": self.last_provider_success_at,
            "last_provider_failure_at": self.last_provider_failure_at,
        }
        self.health_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.health_path.with_name(
            f".{self.health_path.name}.{os.getpid()}.{uuid4().hex}.tmp"
        )
        try:
            tmp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.health_path)
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except OSError as exc:
                logger.debug(
                    "3D worker health temporary file cleanup failed",
                    error_type=type(exc).__name__,
                )

    async def preflight(self) -> None:
        await asyncio.to_thread(self.storage.preflight)
        async with SessionLocal() as session:
            policy = await get_three_d_policy(session)
            await session.execute(select(ThreeDGenerationJob.id).limit(1))
        candidates: list[str] = []
        if "hunyuan3d" in self.runpods:
            candidates.append("hunyuan3d")
        if policy.get("fallback_enabled", True) and "triposr" in self.runpods:
            candidates.append("triposr")
        if not candidates:
            raise ThreeDWorkerError("No enabled 3D provider endpoint is configured")
        healthy: list[str] = []
        for provider in candidates:
            client = self._client_for_provider(provider)
            try:
                health = await asyncio.to_thread(client.health)
            except Exception as exc:
                logger.warning(
                    "3D provider preflight failed",
                    provider=provider,
                    error_type=type(exc).__name__,
                )
                continue
            if isinstance(health, dict):
                healthy.append(provider)
            else:
                logger.warning(
                    "3D provider preflight response is invalid", provider=provider
                )
        if not healthy:
            raise ThreeDWorkerError("No enabled 3D provider passed preflight")

    async def claim(self) -> tuple[str, str] | None:
        async with SessionLocal() as session:
            blocked_provider_values: set[str] = set()
            for provider in ("hunyuan3d", "triposr"):
                state = await provider_circuit_snapshot(session, provider=provider)
                if state["state"] != "open":
                    continue
                blocked_provider_values.add(provider)
                if provider == "hunyuan3d":
                    blocked_provider_values.add("runpod")
            provider_gate: ColumnElement[bool] = ThreeDGenerationJob.id.is_not(None)
            if blocked_provider_values:
                provider_gate = or_(
                    ThreeDGenerationJob.provider_job_id.is_not(None),
                    ThreeDGenerationJob.status == "cancel_requested",
                    ThreeDGenerationJob.provider.notin_(blocked_provider_values),
                )
            job = await session.scalar(
                select(ThreeDGenerationJob)
                .where(
                    or_(
                        and_(
                            ThreeDGenerationJob.status == "queued",
                            ThreeDGenerationJob.attempts
                            < ThreeDGenerationJob.max_attempts,
                        ),
                        and_(
                            ThreeDGenerationJob.status == "running",
                            ThreeDGenerationJob.updated_at < self.stale_before,
                        ),
                        and_(
                            ThreeDGenerationJob.status == "cancel_requested",
                            ThreeDGenerationJob.updated_at < self.stale_before,
                        ),
                    )
                )
                .where(provider_gate)
                .order_by(ThreeDGenerationJob.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if job is None:
                return None
            cancel_reclaim = job.status == "cancel_requested"
            reclaimed = job.status in {"running", "cancel_requested"}
            lease_token = str(uuid4())
            if not reclaimed or (not job.provider_job_id and not cancel_reclaim):
                job.attempts += 1
            job.status = "cancel_requested" if cancel_reclaim else "running"
            job.stage = (
                "cancelling"
                if cancel_reclaim
                else ("provider_queue" if job.provider_job_id else "preparing")
            )
            job.progress = max(job.progress, 2)
            job.lease_token = lease_token
            job.started_at = job.started_at or now()
            job.error_code = None
            job.error_message = None
            job.version += 1
            session.add(
                audit_job(
                    job,
                    "3d.job.worker_claimed",
                    actor_id=None,
                    details={"reclaimed": reclaimed, "attempt": job.attempts},
                )
            )
            await session.commit()
            logger.info(
                "3D job claimed",
                job_id=job.id,
                trace_id=job.trace_id,
                attempt=job.attempts,
                reclaimed=reclaimed,
            )
            return job.id, lease_token

    async def _load(self, job_id: str, lease_token: str) -> ThreeDGenerationJob | None:
        async with SessionLocal() as session:
            return await session.scalar(
                select(ThreeDGenerationJob).where(
                    ThreeDGenerationJob.id == job_id,
                    ThreeDGenerationJob.status.in_({"running", "cancel_requested"}),
                    ThreeDGenerationJob.lease_token == lease_token,
                )
            )

    async def _update_provider_job(
        self, job_id: str, lease_token: str, provider_job_id: str
    ) -> None:
        async with SessionLocal() as session:
            job = await session.scalar(
                select(ThreeDGenerationJob)
                .where(
                    ThreeDGenerationJob.id == job_id,
                    ThreeDGenerationJob.lease_token == lease_token,
                )
                .with_for_update()
            )
            if job is None:
                raise ThreeDWorkerError("3D worker lease was lost")
            job.provider_job_id = provider_job_id
            job.stage = "provider_queue"
            job.progress = max(job.progress, 10)
            job.version += 1
            session.add(audit_job(job, "3d.job.provider_submitted", actor_id=None))
            notes = await notify_job(
                session,
                job,
                event_key="3d.job.processing",
                title="3D generation started",
                message="Your 3D source image is now being processed on the GPU pipeline.",
                include_owner=True,
            )
            await session.commit()
        for item in notes:
            await communications.publish_realtime(item)

    async def _heartbeat(
        self,
        job_id: str,
        lease_token: str,
        *,
        stage: str,
        progress: int,
        status_data: dict | None = None,
    ) -> str:
        async with SessionLocal() as session:
            job = await session.scalar(
                select(ThreeDGenerationJob)
                .where(
                    ThreeDGenerationJob.id == job_id,
                    ThreeDGenerationJob.lease_token == lease_token,
                )
                .with_for_update()
            )
            if job is None:
                raise ThreeDWorkerError("3D worker lease was lost")
            if job.status == "cancel_requested":
                return "cancel_requested"
            job.stage = stage
            job.progress = max(job.progress, min(95, progress))
            if status_data:
                if status_data.get("delayTime") is not None:
                    job.provider_delay_ms = int(status_data["delayTime"])
                if status_data.get("executionTime") is not None:
                    job.provider_execution_ms = int(status_data["executionTime"])
            job.version += 1
            await session.commit()
            return job.status

    async def _cancelled(self, job_id: str, lease_token: str) -> None:
        async with SessionLocal() as session:
            job = await session.scalar(
                select(ThreeDGenerationJob)
                .where(
                    ThreeDGenerationJob.id == job_id,
                    ThreeDGenerationJob.lease_token == lease_token,
                )
                .with_for_update()
            )
            if job is None:
                return
            job.status = "cancelled"
            job.stage = "cancelled"
            job.progress = 100
            job.cancelled_at = now()
            job.completed_at = now()
            job.lease_token = None
            job.version += 1
            session.add(audit_job(job, "3d.job.cancelled", actor_id=None))
            notes = await notify_job(
                session,
                job,
                event_key="3d.job.cancelled",
                title="3D generation cancelled",
                message="The 3D generation job was cancelled safely.",
                include_owner=True,
                severity="warning",
            )
            await session.commit()
            input_key = job.input_object_key
        await asyncio.to_thread(self.storage.delete, input_key)
        for item in notes:
            await communications.publish_realtime(item)

    async def _needs_clarification(self, job_id: str, lease_token: str) -> None:
        async with SessionLocal() as session:
            job = await session.scalar(
                select(ThreeDGenerationJob)
                .where(
                    ThreeDGenerationJob.id == job_id,
                    ThreeDGenerationJob.lease_token == lease_token,
                )
                .with_for_update()
            )
            if job is None:
                return
            job.status = "needs_clarification"
            job.stage = "needs_clarification"
            job.progress = 100
            job.error_code = "THREE_D_SOURCE_CLARIFICATION_REQUIRED"
            job.error_message = "The source image could not be used reliably. Upload a clearer replacement image to continue."
            job.completed_at = now()
            job.lease_token = None
            job.version += 1
            session.add(audit_job(job, "3d.job.clarification_required", actor_id=None))
            notes = await notify_job(
                session,
                job,
                event_key="3d.job.clarification_required",
                title="A clearer image is needed",
                message="The 3D pipeline needs a clearer source image. Open the project and upload a replacement to continue this job.",
                include_owner=True,
                severity="warning",
            )
            await session.commit()
        for item in notes:
            await communications.publish_realtime(item)

    async def _failed(
        self, job_id: str, lease_token: str, code: str, message: str, *, retryable: bool
    ) -> None:
        async with SessionLocal() as session:
            job = await session.scalar(
                select(ThreeDGenerationJob)
                .where(
                    ThreeDGenerationJob.id == job_id,
                    ThreeDGenerationJob.lease_token == lease_token,
                )
                .with_for_update()
            )
            if job is None:
                return
            retry = retryable and job.attempts < job.max_attempts
            if retry:
                job.status = "queued"
                job.stage = "queued"
                job.progress = 0
                job.provider_job_id = None
                job.lease_token = None
                job.error_code = code
                job.error_message = "A temporary provider error occurred; AIOS scheduled a bounded retry."
                job.version += 1
                session.add(
                    audit_job(
                        job,
                        "3d.job.retry_scheduled",
                        actor_id=None,
                        details={"error_code": code, "attempt": job.attempts},
                    )
                )
                await session.commit()
                return
            job.status = "failed"
            job.stage = "failed"
            job.progress = 100
            job.error_code = code
            job.error_message = message
            job.completed_at = now()
            job.lease_token = None
            job.version += 1
            session.add(
                audit_job(
                    job, "3d.job.failed", actor_id=None, details={"error_code": code}
                )
            )
            notes = await notify_job(
                session,
                job,
                event_key="3d.job.failed",
                title="3D generation could not be completed",
                message=message,
                include_owner=True,
                severity="warning",
            )
            await session.commit()
            input_key = job.input_object_key
        await asyncio.to_thread(self.storage.delete, input_key)
        for item in notes:
            await communications.publish_realtime(item)

    async def _complete(self, job_id: str, lease_token: str, status_data: dict) -> None:
        claimed = await self._load(job_id, lease_token)
        if claimed is None:
            return
        provider = claimed.provider
        output = status_data.get("output")
        if not isinstance(output, dict):
            await self._failed(
                job_id,
                lease_token,
                "THREE_D_PROVIDER_OUTPUT_INVALID",
                "The 3D provider returned an invalid result.",
                retryable=True,
            )
            return
        provider_error = str(output.get("error") or "")
        if provider_error:
            if provider_error_requires_clarification(provider_error):
                await self._needs_clarification(job_id, lease_token)
            else:
                await self._failed(
                    job_id,
                    lease_token,
                    "THREE_D_PROVIDER_FAILED",
                    "The 3D provider could not complete this request.",
                    retryable=True,
                )
            return
        manifest = output.get("manifest")
        if not isinstance(manifest, dict) or not _manifest_acceptable(
            provider, manifest
        ):
            await self._failed(
                job_id,
                lease_token,
                "THREE_D_PROVIDER_ARTIFACT_POLICY",
                "The selected 3D provider did not produce an artifact that satisfies its licensed output policy.",
                retryable=True,
            )
            return
        encoded = output.get("content_base64")
        if not isinstance(encoded, str):
            await self._failed(
                job_id,
                lease_token,
                "THREE_D_ARTIFACT_MISSING",
                "The 3D provider did not return an artifact.",
                retryable=True,
            )
            return
        try:
            body = base64.b64decode(encoded, validate=True)
        except ValueError:
            await self._failed(
                job_id,
                lease_token,
                "THREE_D_ARTIFACT_ENCODING",
                "The 3D provider returned an invalid artifact.",
                retryable=True,
            )
            return
        if (
            body[:4] != b"glTF"
            or not body
            or len(body) > settings.THREE_D_MAX_OUTPUT_BYTES
        ):
            await self._failed(
                job_id,
                lease_token,
                "THREE_D_ARTIFACT_INVALID",
                "The generated 3D artifact failed validation.",
                retryable=True,
            )
            return
        digest = sha256(body).hexdigest()
        reported = str(output.get("sha256") or manifest.get("sha256") or "").lower()
        if reported and reported != digest:
            await self._failed(
                job_id,
                lease_token,
                "THREE_D_ARTIFACT_HASH_MISMATCH",
                "The generated 3D artifact failed integrity verification.",
                retryable=True,
            )
            return

        async with SessionLocal() as session:
            job = await session.scalar(
                select(ThreeDGenerationJob)
                .where(
                    ThreeDGenerationJob.id == job_id,
                    ThreeDGenerationJob.lease_token == lease_token,
                )
                .with_for_update()
            )
            if job is None:
                return
            policy = await get_three_d_policy(session)
            output_key = self.storage.output_key(
                job.organization_id, job.project_id, job.id
            )
            organization_id = job.organization_id
            project_id = job.project_id
            requested_by_id = job.requested_by_id
            input_key = job.input_object_key
            execution_ms = int(status_data.get("executionTime") or 0)
            job.stage = "storing_artifact"
            job.progress = 96
            job.provider_delay_ms = int(status_data.get("delayTime") or 0)
            job.provider_execution_ms = execution_ms
            job.estimated_cost_usd = round(
                (execution_ms / 1000.0) * settings.THREE_D_GPU_COST_PER_SECOND_USD, 6
            )
            await session.commit()

        stored = await asyncio.to_thread(
            self.storage.put_bytes,
            output_key,
            body,
            GLB_MEDIA_TYPE,
            metadata={
                "organization_id": organization_id,
                "project_id": project_id,
                "job_id": job_id,
            },
        )
        if stored.sha256 != digest:
            await self._failed(
                job_id,
                lease_token,
                "THREE_D_STORAGE_HASH_MISMATCH",
                "The stored 3D artifact failed integrity verification.",
                retryable=False,
            )
            return

        try:
            async with SessionLocal() as meter_session:
                await billing.record_usage(
                    meter_session,
                    organization_id,
                    metric="3d_generations",
                    quantity=1,
                    idempotency_key=f"3d:{job_id}",
                )
        except Exception:
            await asyncio.to_thread(self.storage.delete, output_key)
            await self._failed(
                job_id,
                lease_token,
                "THREE_D_METERING_FAILED",
                "3D usage metering could not be finalized safely.",
                retryable=True,
            )
            return

        async with SessionLocal() as session:
            job = await session.scalar(
                select(ThreeDGenerationJob)
                .where(
                    ThreeDGenerationJob.id == job_id,
                    ThreeDGenerationJob.lease_token == lease_token,
                )
                .with_for_update()
            )
            if job is None:
                return
            existing = await session.scalar(
                select(ThreeDArtifact).where(ThreeDArtifact.job_id == job.id)
            )
            expires_at = now() + timedelta(days=int(policy["artifact_retention_days"]))
            metadata = {
                "pipeline": manifest.get("pipeline"),
                "seed": manifest.get("seed"),
                "mesh_count": manifest.get("mesh_count"),
                "material_count": manifest.get("material_count"),
                "pbr_material_count": manifest.get("pbr_material_count"),
                "texture_count": manifest.get("texture_count"),
                "texture_size_limit": manifest.get("texture_size_limit"),
                "compression_policy": manifest.get("compression_policy"),
                "optimization_ratio": manifest.get("optimization_ratio"),
                "pre_optimization_bytes": manifest.get("pre_optimization_bytes"),
                "post_optimization_bytes": manifest.get("post_optimization_bytes"),
                "timings": manifest.get("timings") or {},
                "provider_delay_ms": job.provider_delay_ms,
                "provider_execution_ms": job.provider_execution_ms,
                "fallback_used": bool(manifest.get("fallback_used")),
                "fallback_provider": manifest.get("fallback_provider"),
                "model_revision": manifest.get("model_revision"),
                "source_revision": manifest.get("source_revision"),
                "license": manifest.get("license"),
                "provider": job.provider,
                "jurisdiction_country": job.request_options.get("jurisdiction_country"),
                "terms_version": job.request_options.get("third_party_terms_version"),
            }
            if existing is None:
                artifact = ThreeDArtifact(
                    id=uuid_str(),
                    organization_id=job.organization_id,
                    project_id=job.project_id,
                    job_id=job.id,
                    created_by_id=requested_by_id,
                    filename="final.glb",
                    media_type=GLB_MEDIA_TYPE,
                    object_key=output_key,
                    checksum=digest,
                    size_bytes=len(body),
                    status="ready",
                    artifact_metadata=metadata,
                    expires_at=expires_at,
                )
                session.add(artifact)
            else:
                artifact = existing
                artifact.object_key = output_key
                artifact.checksum = digest
                artifact.size_bytes = len(body)
                artifact.status = "ready"
                artifact.artifact_metadata = metadata
                artifact.expires_at = expires_at
            job.status = "completed"
            job.stage = "completed"
            job.progress = 100
            job.metering_status = "metered"
            job.error_code = None
            job.error_message = None
            job.completed_at = now()
            job.lease_token = None
            job.version += 1
            session.add(
                audit_job(
                    job,
                    "3d.job.completed",
                    actor_id=None,
                    details={
                        "artifact_id": artifact.id,
                        "size_bytes": len(body),
                        "sha256": digest,
                        "estimated_cost_usd": job.estimated_cost_usd,
                    },
                )
            )
            notes = await notify_job(
                session,
                job,
                event_key="3d.job.completed",
                title="3D model ready",
                message="Your textured PBR 3D model is ready to preview or download from the project.",
                include_owner=True,
                severity="success",
            )
            await session.commit()
        async with SessionLocal() as spend_session:
            spend_notes = await maybe_emit_spend_alerts(
                spend_session, organization_id=organization_id
            )
            await spend_session.commit()
        await asyncio.to_thread(self.storage.delete, input_key)
        for item in [*notes, *spend_notes]:
            await communications.publish_realtime(item)
        logger.info(
            "3D job completed",
            job_id=job_id,
            trace_id=job.trace_id,
            provider_execution_ms=job.provider_execution_ms,
            provider_delay_ms=job.provider_delay_ms,
            artifact_bytes=len(body),
            estimated_cost_usd=job.estimated_cost_usd,
        )

    async def _provider_failure(
        self, job: ThreeDGenerationJob, error_code: str
    ) -> None:
        async with SessionLocal() as session:
            state, opened = await record_provider_failure(
                session, error_code=error_code, provider=job.provider
            )
            notes = []
            if opened:
                notes = await provider_outage_alert(
                    session,
                    organization_id=job.organization_id,
                    state=state,
                    provider=job.provider,
                )
            await session.commit()
        for item in notes:
            await communications.publish_realtime(item)
        self.circuit_state = str(state.get("state") or "unknown")
        self.last_provider_failure_at = now().isoformat()
        logger.warning(
            "3D provider failure recorded",
            job_id=job.id,
            trace_id=job.trace_id,
            error_code=error_code,
            circuit_state=state.get("state"),
            consecutive_failures=state.get("consecutive_failures"),
        )

    async def _provider_success(self, job: ThreeDGenerationJob) -> None:
        async with SessionLocal() as session:
            state = await record_provider_success(session, provider=job.provider)
            await session.commit()
        self.circuit_state = str(state.get("state") or "closed")
        self.last_provider_success_at = now().isoformat()
        logger.info(
            "3D provider success recorded",
            job_id=job.id,
            trace_id=job.trace_id,
            circuit_state=state.get("state"),
        )

    async def _cleanup_if_due(self) -> None:
        if time.monotonic() < self.next_cleanup_at:
            return
        async with SessionLocal() as session:
            policy = await get_three_d_policy(session)
            interval = int(policy["cleanup_interval_seconds"])
            try:
                result = await cleanup_expired_three_d_data(session, self.storage)
                self.last_cleanup_at = now().isoformat()
                logger.info("3D cleanup completed", **result)
            except Exception as exc:
                await session.rollback()
                logger.warning("3D cleanup failed", error_type=type(exc).__name__)
            finally:
                self.next_cleanup_at = time.monotonic() + interval

    async def _defer_for_open_circuit(
        self, job_id: str, lease_token: str, *, provider: str
    ) -> None:
        async with SessionLocal() as session:
            job = await session.scalar(
                select(ThreeDGenerationJob)
                .where(
                    ThreeDGenerationJob.id == job_id,
                    ThreeDGenerationJob.lease_token == lease_token,
                    ThreeDGenerationJob.provider_job_id.is_(None),
                )
                .with_for_update()
            )
            if job is None:
                return
            job.status = "queued"
            job.stage = "provider_circuit_open"
            job.progress = 0
            job.lease_token = None
            job.attempts = max(0, job.attempts - 1)
            job.error_code = "THREE_D_PROVIDER_CIRCUIT_OPEN"
            job.error_message = (
                "The selected 3D provider is recovering; this job remains queued."
            )
            job.version += 1
            session.add(
                audit_job(
                    job,
                    "3d.job.provider_circuit_deferred",
                    actor_id=None,
                    details={"provider": provider},
                )
            )
            await session.commit()

    async def _defer_for_runtime_gate(
        self, job_id: str, lease_token: str, *, provider: str
    ) -> None:
        async with SessionLocal() as session:
            job = await session.scalar(
                select(ThreeDGenerationJob)
                .where(
                    ThreeDGenerationJob.id == job_id,
                    ThreeDGenerationJob.lease_token == lease_token,
                    ThreeDGenerationJob.provider_job_id.is_(None),
                )
                .with_for_update()
            )
            if job is None:
                return
            job.status = "queued"
            job.stage = "provider_runtime_unverified"
            job.progress = 0
            job.lease_token = None
            job.attempts = max(0, job.attempts - 1)
            job.error_code = "THREE_D_PROVIDER_RUNTIME_UNVERIFIED"
            job.error_message = (
                "The selected 3D provider no longer passes its runtime policy; "
                "this job remains queued without GPU submission."
            )
            job.version += 1
            session.add(
                audit_job(
                    job,
                    "3d.job.provider_runtime_deferred",
                    actor_id=None,
                    details={"provider": provider},
                )
            )
            await session.commit()

    async def _cancel_provider(
        self, provider_job_id: str, *, provider: str, reason: str
    ) -> bool:
        try:
            client = self._client_for_provider(provider)
            await asyncio.to_thread(client.cancel, provider_job_id)
            return True
        except RunPodError as exc:
            logger.warning(
                "3D provider cancellation could not be confirmed",
                provider_job_id=provider_job_id,
                reason=reason,
                error_type=type(exc).__name__,
            )
            return False

    async def execute(self, job_id: str, lease_token: str) -> None:
        job = await self._load(job_id, lease_token)
        if job is None:
            return
        if job.status == "cancel_requested":
            if job.provider_job_id:
                await self._cancel_provider(
                    job.provider_job_id,
                    provider=job.provider,
                    reason="job-cancel-requested",
                )
            await self._cancelled(job_id, lease_token)
            return

        policy = None
        async with SessionLocal() as session:
            policy = await get_three_d_policy(session)
        if not policy["enabled"]:
            if job.provider_job_id:
                await self._cancel_provider(
                    job.provider_job_id,
                    provider=job.provider,
                    reason="owner-service-disabled",
                )
            await self._cancelled(job_id, lease_token)
            return
        max_queue = int(policy["max_queue_seconds"])
        max_runtime = int(policy["max_runtime_seconds"])
        client = self._client_for_provider(job.provider)
        provider_job_id = job.provider_job_id
        if not provider_job_id:
            try:
                async with SessionLocal() as circuit_session:
                    await assert_provider_available(
                        circuit_session, provider=job.provider
                    )
                    await circuit_session.commit()
            except HTTPException as exc:
                if exc.status_code != 503:
                    raise
                await self._defer_for_open_circuit(
                    job_id, lease_token, provider=job.provider
                )
                return
            try:
                image = await asyncio.to_thread(
                    self.storage.get_bytes,
                    job.input_object_key,
                    max_bytes=int(policy["max_input_megabytes"]) * 1024 * 1024,
                )
                payload = {
                    "image": base64.b64encode(image).decode("ascii"),
                    "allow_shape_fallback": False,
                    "seed": int(job.request_options.get("seed") or 12345),
                    "texture_size": min(
                        int(
                            job.request_options.get("texture_size")
                            or policy["max_texture_size"]
                        ),
                        int(policy["max_texture_size"]),
                    ),
                    "compression_policy": str(
                        job.request_options.get("compression_policy")
                        or policy["compression_policy"]
                    ),
                }
                if job.provider == "triposr":
                    payload["mc_resolution"] = 192
                runtime_provider = (
                    "hunyuan3d" if job.provider == "runpod" else job.provider
                )
                if (
                    runtime_provider == "hunyuan3d"
                    and not await provider_runtime_configured(
                        runtime_provider,
                        expected_endpoint_id=client.endpoint_id,
                        bypass_cache=True,
                    )
                ):
                    logger.warning(
                        "3D provider runtime policy failed before submission",
                        job_id=job_id,
                        provider=runtime_provider,
                    )
                    await self._provider_failure(
                        job, "THREE_D_PROVIDER_RUNTIME_UNVERIFIED"
                    )
                    await self._defer_for_runtime_gate(
                        job_id, lease_token, provider=job.provider
                    )
                    return
                result = await asyncio.to_thread(
                    client.submit, payload, ttl_seconds=max_runtime + max_queue
                )
                provider_job_id = str(result.get("id") or "")
                if not provider_job_id:
                    raise RunPodError("Provider job id missing")
                await self._update_provider_job(job_id, lease_token, provider_job_id)
                logger.info(
                    "3D job submitted to provider",
                    job_id=job.id,
                    trace_id=job.trace_id,
                    provider_job_id=provider_job_id,
                )
            except (RunPodError, ThreeDStorageError, OSError) as exc:
                if isinstance(exc, RunPodError):
                    await self._provider_failure(job, "THREE_D_SUBMIT_FAILED")
                logger.warning(
                    "3D submission failed", job_id=job_id, error_type=type(exc).__name__
                )
                await self._failed(
                    job_id,
                    lease_token,
                    "THREE_D_SUBMIT_FAILED",
                    "The 3D job could not be submitted to the GPU provider.",
                    retryable=True,
                )
                return

        queue_started = time.monotonic()
        poll_started = queue_started
        running_started: float | None = None
        while not self.stop_event.is_set():
            async with SessionLocal() as policy_session:
                policy = await get_three_d_policy(policy_session)
            max_queue = int(policy["max_queue_seconds"])
            max_runtime = int(policy["max_runtime_seconds"])
            if not policy["enabled"]:
                await self._cancel_provider(
                    provider_job_id,
                    provider=job.provider,
                    reason="owner-service-disabled-during-poll",
                )
                await self._cancelled(job_id, lease_token)
                return
            try:
                data = await asyncio.to_thread(client.status, provider_job_id)
            except RunPodError as exc:
                logger.warning(
                    "3D provider status failed",
                    job_id=job_id,
                    trace_id=job.trace_id,
                    error_type=type(exc).__name__,
                )
                await self._provider_failure(job, "THREE_D_PROVIDER_STATUS_ERROR")
                if time.monotonic() - poll_started > max_queue + max_runtime + 60:
                    await self._failed(
                        job_id,
                        lease_token,
                        "THREE_D_PROVIDER_STATUS_TIMEOUT",
                        "The 3D provider stopped reporting job status.",
                        retryable=True,
                    )
                    return
                await asyncio.sleep(5)
                continue
            state = str(data.get("status") or "").upper()
            if state == "COMPLETED":
                await self._provider_success(job)
                await self._complete(job_id, lease_token, data)
                return
            if state in {"FAILED", "TIMED_OUT", "CANCELLED"}:
                if state != "CANCELLED":
                    await self._provider_failure(job, f"THREE_D_PROVIDER_{state}")
                await self._failed(
                    job_id,
                    lease_token,
                    f"THREE_D_PROVIDER_{state}",
                    _safe_provider_message(state),
                    retryable=state != "CANCELLED",
                )
                return
            if state == "IN_PROGRESS" and running_started is None:
                running_started = time.monotonic()
            progress = (
                20 if state == "IN_QUEUE" else 55 if state == "IN_PROGRESS" else 15
            )
            current = await self._heartbeat(
                job_id,
                lease_token,
                stage="provider_queue" if state == "IN_QUEUE" else "generating_pbr",
                progress=progress,
                status_data=data,
            )
            if current == "cancel_requested":
                await self._cancel_provider(
                    provider_job_id,
                    provider=job.provider,
                    reason="user-cancel-requested",
                )
                await self._cancelled(job_id, lease_token)
                return
            if state == "IN_QUEUE" and time.monotonic() - queue_started > max_queue:
                await self._cancel_provider(
                    provider_job_id, provider=job.provider, reason="queue-timeout"
                )
                await self._provider_failure(job, "THREE_D_QUEUE_TIMEOUT")
                await self._failed(
                    job_id,
                    lease_token,
                    "THREE_D_QUEUE_TIMEOUT",
                    "The 3D provider queue exceeded the Owner-defined wait limit.",
                    retryable=True,
                )
                return
            if (
                running_started is not None
                and time.monotonic() - running_started > max_runtime
            ):
                await self._cancel_provider(
                    provider_job_id, provider=job.provider, reason="runtime-timeout"
                )
                await self._provider_failure(job, "THREE_D_RUNTIME_TIMEOUT")
                await self._failed(
                    job_id,
                    lease_token,
                    "THREE_D_RUNTIME_TIMEOUT",
                    "The 3D generation exceeded the Owner-defined runtime limit.",
                    retryable=True,
                )
                return
            if time.monotonic() - poll_started > max_queue + max_runtime + 60:
                await self._cancel_provider(
                    provider_job_id,
                    provider=job.provider,
                    reason="total-provider-timeout",
                )
                await self._provider_failure(job, "THREE_D_PROVIDER_TIMEOUT")
                await self._failed(
                    job_id,
                    lease_token,
                    "THREE_D_PROVIDER_TIMEOUT",
                    "The 3D provider exceeded the total allowed processing window.",
                    retryable=True,
                )
                return
            await asyncio.sleep(5)

    async def run_once(self) -> bool:
        await self._cleanup_if_due()
        claim = await self.claim()
        if claim is None:
            return False
        try:
            await self.execute(*claim)
        except Exception as exc:
            self.errors += 1
            logger.exception(
                "3D worker cycle failed", job_id=claim[0], error_type=type(exc).__name__
            )
            try:
                await self._failed(
                    claim[0],
                    claim[1],
                    "THREE_D_WORKER_ERROR",
                    "The 3D worker stopped this attempt safely.",
                    retryable=True,
                )
            except Exception:
                logger.exception(
                    "3D worker could not persist failure state", job_id=claim[0]
                )
        self.cycles += 1
        self.write_health("ok")
        return True


async def healthcheck() -> int:
    try:
        worker = ThreeDGenerationWorker()
        await worker.preflight()
        return 0
    except Exception:
        logger.exception("3D worker healthcheck failed")
        return 1


async def run_worker() -> None:
    worker = ThreeDGenerationWorker()
    await worker.preflight()
    worker.write_health("ok")
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, worker.stop_event.set)
        except NotImplementedError:
            logger.debug(
                "Signal handlers are unavailable on this runtime", signal=signum.name
            )
    logger.info("3D generation worker started")
    while not worker.stop_event.is_set():
        processed = await worker.run_once()
        if processed:
            continue
        try:
            await asyncio.wait_for(
                worker.stop_event.wait(), timeout=settings.THREE_D_WORKER_POLL_SECONDS
            )
        except TimeoutError:
            continue
    logger.info("3D generation worker stopped")


def main() -> int:
    setup_logging()
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--healthcheck", action="store_true")
    args, _ = parser.parse_known_args()
    if args.healthcheck:
        return asyncio.run(healthcheck())
    asyncio.run(run_worker())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
