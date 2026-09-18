"""Durable provider-neutral Production Studio worker for Phase 29H."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import time
from datetime import UTC, datetime
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
    StudioExecution,
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
from sqlalchemy import select

from app.services.host_maintenance_admission import HostMaintenanceClosed, SessionFactory
from app.services.host_maintenance_studio_admission import require_studio_admission
from app.services import studio_resource_registry as studio_registry
from app.services.studio_execution_guard import (
    GUARD_KEY, PROTOCOL, execution_guard, pristine_conditions, set_phase,
)

logger = get_logger(__name__)


def now() -> datetime:
    return datetime.now(UTC)


class StudioWorker:
    def __init__(self, *, session_factory: SessionFactory | None = None) -> None:
        self._session_factory = session_factory
        self.incarnation = str(uuid4())
        self.stop_event = asyncio.Event()
        self.health_path = Path(settings.STUDIO_WORKER_HEALTH_FILE)
        self.cycles = 0
        self.errors = 0

    @property
    def sessions(self) -> SessionFactory:
        return self._session_factory or SessionLocal

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
        async with self.sessions() as session:
            await session.execute(select(StudioJob.id).limit(1))

    async def claim(self) -> tuple[str, str] | None:
        return await self._claim()

    async def _claim(self, job_id: str | None = None) -> tuple[str, str] | None:
        """Commit admission, untouched-job claim and provenance before I/O."""
        async with self.sessions() as session:
            authority = await require_studio_admission(session)
            statement = select(StudioJob).where(
                *pristine_conditions(),
                ~select(StudioExecution.id).where(StudioExecution.job_id == StudioJob.id).exists(),
            )
            if job_id is not None:
                statement = statement.where(StudioJob.id == job_id)
            statement = statement.order_by(StudioJob.created_at, StudioJob.id)
            job = await session.scalar(statement.with_for_update(skip_locked=True).limit(1))
            if job is None:
                return None
            nonce = str(uuid4())
            await studio_registry.register_claim(
                session, job_id=job.id, nonce=nonce, worker_incarnation=self.incarnation,
            )
            job.status = "running"
            job.progress = 10
            job.started_at = now()
            job.lease_token = nonce
            job.attempts = 1
            job.result_metadata = {
                GUARD_KEY: {
                    "protocol_version": PROTOCOL, "phase": "claimed",
                    "worker_incarnation": self.incarnation,
                    "admitted_generation": authority.generation,
                    "cleanup_verified": False,
                },
            }
            session.add(AuditEvent(
                organization_id=job.organization_id, user_id=None,
                action="studio.job.claimed", resource_type="studio_job",
                resource_id=job.id,
                details={"attempt": 1, "reclaimed": False, "provider_mode": job.provider_mode},
            ))
            await session.commit()
            return job.id, nonce

    async def _begin_execution(self, job_id: str, nonce: str) -> bool:
        """Exactly one start, by its claiming incarnation and authority generation."""
        async with self.sessions() as session:
            authority = await require_studio_admission(session)
            job = await session.scalar(select(StudioJob).where(
                StudioJob.id == job_id, StudioJob.status == "running",
                StudioJob.lease_token == nonce, StudioJob.attempts == 1,
                StudioJob.completed_at.is_(None), StudioJob.cancelled_at.is_(None),
            ).with_for_update())
            if job is None:
                return False
            guard = execution_guard(job)
            if (
                guard is None or guard["phase"] != "claimed"
                or guard["worker_incarnation"] != self.incarnation
                or guard["admitted_generation"] != authority.generation
            ):
                return False
            if not await studio_registry.begin_registered(
                session, job_id=job_id, nonce=nonce, worker_incarnation=self.incarnation,
                admitted_generation=authority.generation,
            ):
                return False
            set_phase(job, "executing")
            await session.commit()
            return True

    async def _mark_unresolved(self, job_id: str, nonce: str, reason: str) -> None:
        """Keep any possible execution as a blocker, never schedule a retry."""
        async with self.sessions() as session:
            job = await session.scalar(select(StudioJob).where(
                StudioJob.id == job_id,
            ).with_for_update())
            if job is None:
                return
            guard = execution_guard(job)
            if (
                guard is None or guard["worker_incarnation"] != self.incarnation
                or guard["phase"] not in {"executing", "unresolved"}
                or job.lease_token != nonce
            ):
                return
            if guard["phase"] == "unresolved" and job.error_code == "STUDIO_RECONCILIATION_REQUIRED":
                # A later wrapper return must not replace the first failure evidence.
                return
            set_phase(job, "unresolved")
            job.error_code = "STUDIO_RECONCILIATION_REQUIRED"
            job.error_message = reason[:160]
            if job.status in {"running", "cancel_requested"}:
                job.completed_at = None
            await session.commit()


    async def claim_by_id(self, job_id: str) -> tuple[str, str] | None:
        """Use the identical no-replay contract for legacy synchronous requests."""
        return await self._claim(job_id)


    async def _load_claim(self, job_id: str, lease_token: str) -> StudioJob | None:
        async with self.sessions() as session:
            job = await session.scalar(select(StudioJob).where(
                StudioJob.id == job_id, StudioJob.status == "running",
                StudioJob.lease_token == lease_token,
            ))
            if job is None:
                return None
            guard = execution_guard(job)
            if guard is None or guard["phase"] != "executing" or guard["worker_incarnation"] != self.incarnation:
                return None
            return job


    async def _blocked(self, job_id: str, lease_token: str, review: dict) -> None:
        async with self.sessions() as session:
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
            set_phase(job, "returned")
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
        # A generation/storage failure does not prove that filesystem work stopped.
        # Keep the exact attempt visible; the full resource settlement is separate.
        await self._mark_unresolved(job_id, lease_token, code)


    async def execute(self, job_id: str, lease_token: str) -> None:
        # Never retry a begin whose commit acknowledgement is missing. No I/O is
        # dispatched before its successful acknowledgement, and the claim remains.
        if not await self._begin_execution(job_id, lease_token):
            return
        try:
            await self._execute_claimed(job_id, lease_token)
        except BaseException as exc:
            try:
                await studio_registry.observe_execution_end(
                    session_factory=self.sessions, job_id=job_id, nonce=lease_token,
                    worker_incarnation=self.incarnation, interrupted=True,
                )
                await self._mark_unresolved(job_id, lease_token, type(exc).__name__)
            except BaseException as evidence_error:
                # Repeated cancellation during evidence persistence must not
                # replace the first interruption or its function-failure cause.
                exc.add_note(
                    f"Studio interruption observation unavailable: {type(evidence_error).__name__}"
                )
                logger.error("Studio interruption evidence unavailable", error_type=type(evidence_error).__name__)
            raise
        await studio_registry.observe_execution_end(
            session_factory=self.sessions, job_id=job_id, nonce=lease_token,
            worker_incarnation=self.incarnation, interrupted=False,
        )
        # A return without a committed terminal result is still unresolved.
        await self._mark_unresolved(job_id, lease_token, "execution_returned_without_terminal_result")

    async def _execute_claimed(self, job_id: str, lease_token: str) -> None:
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
            async with self.sessions() as session:
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
            artifact = await studio_registry.owned_studio_thread(
                self.sessions, job_id, lease_token, self.incarnation, "build_archive",
                build_archive, spec, job_id=job.id, revision_number=revision_number,
            )
            path = await studio_registry.owned_studio_thread(
                self.sessions, job_id, lease_token, self.incarnation, "store_artifact",
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

        async with self.sessions() as session:
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
                # A pathname is not proof of file ownership. Preserve the output
                # and durable attempt for later identity-bound reconciliation.
                logger.warning("Studio artifact retained for owned reconciliation")
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
                **locked.result_metadata,
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
            set_phase(locked, "returned")
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
        try:
            claim = await self.claim()
        except HostMaintenanceClosed:
            return False
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
                # Keep the liveness receipt fresh even when the queue is idle.
                self.write_health("running")
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
            logger.debug("Studio signal handler unsupported")
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
