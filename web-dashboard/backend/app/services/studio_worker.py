"""Durable provider-neutral Production Studio worker for Phase 29H."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.db.base import SessionLocal
from app.db.models import (
    AuditEvent,
    Notification,
    Project,
    ProjectEvent,
    StudioAsset,
    StudioAssetRevision,
    StudioJob,
    StudioSafetyReview,
    uuid_str,
)
from app.services.production_studio import (
    ASSET_TYPES,
    POLICY_VERSION,
    StudioSpec,
    build_archive,
    safety_review,
    store_artifact,
)
from sqlalchemy import and_, or_, select

logger = get_logger(__name__)


def now() -> datetime:
    return datetime.now(UTC)


class StudioWorker:
    def __init__(self) -> None:
        self.stop_event = asyncio.Event()
        self.health_path = Path(settings.STUDIO_WORKER_HEALTH_FILE)
        self.cycles = 0
        self.errors = 0

    @property
    def stale_before(self) -> datetime:
        return now() - timedelta(seconds=settings.STUDIO_JOB_LEASE_SECONDS)

    def write_health(self, status: str) -> None:
        payload = {
            "status": status,
            "checked_at": now().isoformat(),
            "checked_at_epoch": time.time(),
            "cycles": self.cycles,
            "errors": self.errors,
            "secret_returned": False,
        }
        self.health_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.health_path.with_name(f".{self.health_path.name}.tmp")
        temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.replace(temporary, self.health_path)

    async def preflight(self) -> None:
        root = Path(settings.STUDIO_ASSET_ROOT)
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        test_path = root / ".studio-worker-preflight"
        test_path.write_text("ok", encoding="utf-8")
        test_path.unlink()
        async with SessionLocal() as session:
            await session.execute(select(StudioJob.id).limit(1))

    async def claim(self) -> tuple[str, str] | None:
        async with SessionLocal() as session:
            job = await session.scalar(
                select(StudioJob)
                .where(
                    or_(
                        StudioJob.status == "queued",
                        and_(
                            StudioJob.status == "running",
                            StudioJob.updated_at < self.stale_before,
                        ),
                    ),
                    StudioJob.attempts < StudioJob.max_attempts,
                )
                .order_by(StudioJob.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if job is None:
                return None
            lease_token = str(uuid4())
            reclaimed = job.status == "running"
            job.status = "running"
            job.progress = 10
            job.started_at = job.started_at or now()
            job.lease_token = lease_token
            job.attempts += 1
            job.error_code = None
            job.error_message = None
            session.add(
                AuditEvent(
                    organization_id=job.organization_id,
                    user_id=None,
                    action="studio.job.claimed",
                    resource_type="studio_job",
                    resource_id=job.id,
                    details={"attempt": job.attempts, "reclaimed": reclaimed, "provider_mode": job.provider_mode},
                )
            )
            await session.commit()
            return job.id, lease_token

    async def claim_by_id(self, job_id: str) -> tuple[str, str] | None:
        """Claim a specific queued job for the legacy synchronous endpoint."""
        async with SessionLocal() as session:
            job = await session.scalar(
                select(StudioJob)
                .where(
                    StudioJob.id == job_id,
                    StudioJob.status == "queued",
                    StudioJob.attempts < StudioJob.max_attempts,
                )
                .with_for_update()
            )
            if job is None:
                return None
            lease_token = str(uuid4())
            job.status = "running"
            job.progress = 10
            job.started_at = job.started_at or now()
            job.lease_token = lease_token
            job.attempts += 1
            await session.commit()
            return job.id, lease_token

    async def _load_claim(self, job_id: str, lease_token: str) -> StudioJob | None:
        async with SessionLocal() as session:
            return await session.scalar(
                select(StudioJob).where(
                    StudioJob.id == job_id,
                    StudioJob.status == "running",
                    StudioJob.lease_token == lease_token,
                )
            )

    async def _blocked(self, job_id: str, lease_token: str, review: dict) -> None:
        async with SessionLocal() as session:
            job = await session.scalar(
                select(StudioJob)
                .where(
                    StudioJob.id == job_id,
                    StudioJob.status == "running",
                    StudioJob.lease_token == lease_token,
                )
                .with_for_update()
            )
            if job is None:
                return
            job.status = "blocked"
            job.progress = 100
            job.safety_status = "blocked"
            job.safety_findings = review["findings"]
            job.error_code = "STUDIO_SAFETY_BLOCKED"
            job.error_message = "The request was blocked by the Production Studio safety policy"
            job.completed_at = now()
            job.lease_token = None
            session.add(
                StudioSafetyReview(
                    id=uuid_str(),
                    organization_id=job.organization_id,
                    job_id=job.id,
                    reviewer_id=None,
                    policy_version=POLICY_VERSION,
                    status="blocked",
                    categories=review["categories"],
                    findings=review["findings"],
                    evidence=review["evidence"],
                    reviewed_at=now(),
                )
            )
            session.add(
                AuditEvent(
                    organization_id=job.organization_id,
                    user_id=None,
                    action="studio.job.blocked",
                    resource_type="studio_job",
                    resource_id=job.id,
                    details={"categories": review["categories"], "status": "blocked"},
                )
            )
            session.add(
                Notification(
                    id=uuid_str(),
                    organization_id=job.organization_id,
                    recipient_id=job.requested_by_id,
                    type="studio_job_blocked",
                    category="studio",
                    event_key="studio.job.blocked",
                    audience="user",
                    title="Production Studio request blocked",
                    message=f"{job.title} was blocked by the Studio safety policy.",
                    severity="warning",
                    source_type="studio_job",
                    source_id=job.id,
                    correlation_id=job.id,
                    dedupe_key=f"studio-blocked:{job.id}",
                    payload={"job_id": job.id, "categories": review["categories"]},
                )
            )
            await session.commit()

    async def _failed(self, job_id: str, lease_token: str, code: str, message: str) -> None:
        async with SessionLocal() as session:
            job = await session.scalar(
                select(StudioJob)
                .where(StudioJob.id == job_id, StudioJob.lease_token == lease_token)
                .with_for_update()
            )
            if job is None:
                return
            terminal = job.attempts >= job.max_attempts
            job.status = "failed" if terminal else "queued"
            job.progress = 0 if not terminal else 100
            job.error_code = code
            job.error_message = message
            job.completed_at = now() if terminal else None
            job.lease_token = None
            session.add(
                AuditEvent(
                    organization_id=job.organization_id,
                    user_id=None,
                    action="studio.job.failed" if terminal else "studio.job.retry_scheduled",
                    resource_type="studio_job",
                    resource_id=job.id,
                    details={"code": code, "attempt": job.attempts, "terminal": terminal},
                )
            )
            if terminal:
                session.add(
                    Notification(
                        id=uuid_str(),
                        organization_id=job.organization_id,
                        recipient_id=job.requested_by_id,
                        type="studio_job_failed",
                        category="studio",
                        event_key="studio.job.failed",
                        audience="user",
                        title="Production Studio job failed",
                        message=f"{job.title} could not be produced after {job.attempts} attempt(s).",
                        severity="warning",
                        source_type="studio_job",
                        source_id=job.id,
                        correlation_id=job.id,
                        dedupe_key=f"studio-failed:{job.id}",
                        payload={"job_id": job.id, "error_code": code},
                    )
                )
            await session.commit()

    async def execute(self, job_id: str, lease_token: str) -> None:
        job = await self._load_claim(job_id, lease_token)
        if job is None:
            return
        spec = StudioSpec(
            department=job.department,
            title=job.title,
            brief=job.brief,
            language=job.language,
            style=job.style,
            target=job.target,
            programming_language=job.programming_language,
        )
        review = safety_review(spec)
        if review["status"] != "passed":
            await self._blocked(job_id, lease_token, review)
            return

        asset_id = job.revision_of_asset_id or uuid_str()
        revision_number = 1
        if job.revision_of_asset_id:
            async with SessionLocal() as session:
                existing = await session.scalar(
                    select(StudioAsset).where(
                        StudioAsset.id == job.revision_of_asset_id,
                        StudioAsset.organization_id == job.organization_id,
                    )
                )
                if existing is None:
                    await self._failed(job_id, lease_token, "STUDIO_ASSET_NOT_FOUND", "The revision target is unavailable")
                    return
                revision_number = existing.current_revision + 1
        try:
            artifact = await asyncio.to_thread(build_archive, spec, job_id=job.id, revision_number=revision_number)
            path = await asyncio.to_thread(
                store_artifact,
                organization_id=job.organization_id,
                asset_id=asset_id,
                revision_number=revision_number,
                artifact=artifact,
            )
        except PermissionError:
            await self._blocked(job_id, lease_token, review)
            return
        except Exception as exc:
            logger.error("Studio artifact generation failed", error_type=type(exc).__name__)
            await self._failed(job_id, lease_token, "STUDIO_GENERATION_FAILED", "The provider-neutral package could not be generated")
            return

        async with SessionLocal() as session:
            locked = await session.scalar(
                select(StudioJob)
                .where(
                    StudioJob.id == job_id,
                    StudioJob.status == "running",
                    StudioJob.lease_token == lease_token,
                )
                .with_for_update()
            )
            if locked is None:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
                return

            if locked.revision_of_asset_id:
                asset = await session.scalar(
                    select(StudioAsset)
                    .where(
                        StudioAsset.id == locked.revision_of_asset_id,
                        StudioAsset.organization_id == locked.organization_id,
                    )
                    .with_for_update()
                )
                if asset is None:
                    await session.rollback()
                    await self._failed(job_id, lease_token, "STUDIO_ASSET_NOT_FOUND", "The revision target is unavailable")
                    return
                asset.current_revision = revision_number
                asset.filename = artifact.filename
                asset.storage_path = str(path)
                asset.checksum = artifact.checksum
                asset.size_bytes = artifact.size_bytes
                asset.media_type = artifact.media_type
                asset.asset_metadata = {**(asset.asset_metadata or {}), "manifest": artifact.manifest, "last_revision_job_id": locked.id}
                asset.status = "active"
                asset.archived_at = None
            else:
                asset = StudioAsset(
                    id=asset_id,
                    organization_id=locked.organization_id,
                    job_id=locked.id,
                    project_id=locked.project_id,
                    created_by_id=locked.requested_by_id,
                    department=locked.department,
                    asset_type=ASSET_TYPES[locked.department],
                    title=locked.title,
                    filename=artifact.filename,
                    media_type=artifact.media_type,
                    storage_path=str(path),
                    checksum=artifact.checksum,
                    size_bytes=artifact.size_bytes,
                    status="active",
                    current_revision=1,
                    asset_metadata={"manifest": artifact.manifest},
                )
                session.add(asset)

            revision = StudioAssetRevision(
                id=uuid_str(),
                organization_id=locked.organization_id,
                asset_id=asset.id,
                job_id=locked.id,
                created_by_id=locked.requested_by_id,
                revision_number=revision_number,
                filename=artifact.filename,
                media_type=artifact.media_type,
                storage_path=str(path),
                checksum=artifact.checksum,
                size_bytes=artifact.size_bytes,
                change_note=locked.change_note,
                revision_metadata={"manifest": artifact.manifest},
                status="active",
            )
            session.add(revision)
            session.add(
                StudioSafetyReview(
                    id=uuid_str(),
                    organization_id=locked.organization_id,
                    job_id=locked.id,
                    asset_id=asset.id,
                    reviewer_id=None,
                    policy_version=POLICY_VERSION,
                    status="passed",
                    categories=[],
                    findings=[],
                    evidence=review["evidence"],
                    reviewed_at=now(),
                )
            )
            locked.status = "completed"
            locked.progress = 100
            locked.safety_status = "passed"
            locked.safety_findings = []
            locked.result_metadata = {
                "asset_id": asset.id,
                "revision_id": revision.id,
                "revision_number": revision_number,
                "checksum": artifact.checksum,
                "size_bytes": artifact.size_bytes,
                "provider_mode": "provider_neutral",
                "external_requests": 0,
                "external_tokens": 0,
                "external_cost_usd": 0,
            }
            locked.completed_at = now()
            locked.lease_token = None
            locked.version += 1
            session.add(
                AuditEvent(
                    organization_id=locked.organization_id,
                    user_id=None,
                    action="studio.job.completed",
                    resource_type="studio_asset",
                    resource_id=asset.id,
                    details={"job_id": locked.id, "revision": revision_number, "checksum": artifact.checksum, "provider_mode": "provider_neutral"},
                )
            )
            if locked.project_id:
                project = await session.get(Project, locked.project_id)
                if project is not None and project.organization_id == locked.organization_id:
                    session.add(
                        ProjectEvent(
                            id=uuid_str(),
                            organization_id=locked.organization_id,
                            project_id=project.id,
                            actor_id=locked.requested_by_id,
                            event_type="studio.asset.generated",
                            summary=f"Production Studio asset generated: {locked.title}",
                            details={"asset_id": asset.id, "job_id": locked.id, "revision": revision_number},
                            created_at=now(),
                        )
                    )
            session.add(
                Notification(
                    id=uuid_str(),
                    organization_id=locked.organization_id,
                    recipient_id=locked.requested_by_id,
                    type="studio_job_completed",
                    category="studio",
                    event_key="studio.job.completed",
                    audience="user",
                    title="Production Studio asset ready",
                    message=f"{locked.title} is ready to download.",
                    severity="info",
                    source_type="studio_asset",
                    source_id=asset.id,
                    correlation_id=locked.id,
                    dedupe_key=f"studio-completed:{locked.id}",
                    payload={"job_id": locked.id, "asset_id": asset.id, "revision": revision_number},
                )
            )
            await session.commit()

    async def run_once(self) -> bool:
        claim = await self.claim()
        if claim is None:
            return False
        await self.execute(*claim)
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
                logger.error("Studio worker cycle failed", error_type=type(exc).__name__)
                self.write_health("degraded")
                processed = False
            if processed:
                continue
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=settings.STUDIO_WORKER_POLL_SECONDS)
            except TimeoutError:
                pass
        self.write_health("stopped")


def healthcheck(path: str | Path, maximum_age_seconds: float | None = None) -> int:
    maximum_age = maximum_age_seconds or max(90.0, float(settings.STUDIO_WORKER_POLL_SECONDS) * 30.0)
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        age = time.time() - float(payload["checked_at_epoch"])
        healthy = payload.get("status") == "running" and 0 <= age <= maximum_age
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        healthy = False
    return 0 if healthy else 1


async def async_main() -> int:
    worker = StudioWorker()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, worker.stop_event.set)
        except NotImplementedError:
            pass
    await worker.run_forever()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--healthcheck", action="store_true")
    args = parser.parse_args()
    if args.healthcheck:
        return healthcheck(settings.STUDIO_WORKER_HEALTH_FILE)
    setup_logging()
    try:
        return asyncio.run(async_main())
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        logger.error("Studio worker startup failed", error_type=type(exc).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
