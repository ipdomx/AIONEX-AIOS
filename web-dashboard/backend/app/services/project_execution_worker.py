"""Durable worker for the complete governed project lifecycle."""

from __future__ import annotations

import asyncio
import signal
import sys
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.db.base import SessionLocal
from app.db.models import (
    AuditEvent,
    Notification,
    OwnerControlRecord,
    Project,
    ProjectExecution,
    ThreeDArtifact,
)
from app.services.project_execution import (
    ProjectPlanningRunner,
    ProjectExecutionConfigurationError,
    sanitized_execution_error,
)
from app.services.three_d_storage import ThreeDObjectStore
from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)
SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


def _now() -> datetime:
    return datetime.now(UTC)


class ProjectExecutionLeaseLost(RuntimeError):
    """The durable execution lease was reclaimed or cancelled."""


class ProjectExecutionWorker:
    def __init__(
        self,
        *,
        runner: ProjectPlanningRunner | None = None,
        session_factory: SessionFactory = SessionLocal,
    ) -> None:
        self.runner = runner or ProjectPlanningRunner()
        self.session_factory = session_factory

    @property
    def stale_before(self) -> datetime:
        return _now() - timedelta(seconds=settings.PROJECT_EXECUTION_JOB_LEASE_SECONDS)

    @staticmethod
    def _uses_postgresql(session: AsyncSession) -> bool:
        get_bind = getattr(session, "get_bind", None)
        if not callable(get_bind):
            return False
        bind = get_bind()
        return getattr(getattr(bind, "dialect", None), "name", None) == "postgresql"

    def _database_timestamp(self, session: AsyncSession) -> Any:
        return func.now() if self._uses_postgresql(session) else _now()

    async def claim(self) -> tuple[str, str] | None:
        async with self.session_factory() as session:
            timestamp = self._database_timestamp(session)
            stale_before = (
                func.now() - timedelta(seconds=settings.PROJECT_EXECUTION_JOB_LEASE_SECONDS)
                if self._uses_postgresql(session)
                else self.stale_before
            )
            record = await session.scalar(
                select(ProjectExecution)
                .where(
                    or_(
                        ProjectExecution.status == "queued",
                        and_(
                            ProjectExecution.status == "running",
                            ProjectExecution.updated_at < stale_before,
                        ),
                    )
                )
                .order_by(ProjectExecution.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if record is None:
                return None
            reclaimed = record.status == "running"
            lease_token = str(uuid4())
            if not reclaimed:
                record.attempts += 1
            record.status = "running"
            record.stage = "intake"
            record.progress = max(record.progress, 2)
            record.lease_token = lease_token
            record.started_at = record.started_at or _now()
            record.updated_at = timestamp
            project = await session.scalar(
                select(Project).where(Project.id == record.project_id).with_for_update()
            )
            if project is not None:
                project.status = "in_progress"
                project.progress = max(project.progress, 5)
            session.add(
                AuditEvent(
                    organization_id=record.organization_id,
                    user_id=None,
                    action="project.execution.worker_claimed",
                    resource_type="project_execution",
                    resource_id=record.id,
                    details={"reclaimed": reclaimed, "attempts": record.attempts},
                )
            )
            await session.commit()
            return record.id, lease_token

    async def renew(self, execution_id: str, lease_token: str) -> None:
        async with self.session_factory() as session:
            record = await session.scalar(
                select(ProjectExecution)
                .where(
                    ProjectExecution.id == execution_id,
                    ProjectExecution.status == "running",
                    ProjectExecution.lease_token == lease_token,
                )
                .with_for_update()
            )
            if record is None:
                raise ProjectExecutionLeaseLost(execution_id)
            record.updated_at = self._database_timestamp(session)
            await session.commit()

    async def load_payload(self, execution_id: str, lease_token: str) -> dict[str, str]:
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(ProjectExecution, Project.name)
                    .join(Project, Project.id == ProjectExecution.project_id)
                    .where(
                        ProjectExecution.id == execution_id,
                        ProjectExecution.status == "running",
                        ProjectExecution.lease_token == lease_token,
                    )
                )
            ).one_or_none()
            if row is None:
                raise ProjectExecutionLeaseLost(execution_id)
            record, project_name = row
            return {
                "job_id": record.id,
                "project_id": record.project_id,
                "project_name": project_name,
                "objective": record.objective,
                "tenant_id": record.organization_id,
                "requested_by_id": record.requested_by_id,
                "execution_mode": record.mode,
            }

    async def prepare_three_d_assets(
        self,
        *,
        execution_id: str,
        lease_token: str,
        project_id: str,
    ) -> str:
        """Stage immutable project GLBs for a full 3D web build.

        The stage is idempotent and bounded. Source objects remain private in S3; only
        integrity-verified copies enter the execution evidence volume.
        """
        from hashlib import sha256
        import json
        import os
        from pathlib import Path

        root = Path(settings.PROJECT_EXECUTION_OUTPUT_ROOT) / execution_id / "three-d-input"
        manifest_path = root / "manifest.json"
        if manifest_path.is_file() and not manifest_path.is_symlink():
            return str(manifest_path)
        if root.exists():
            raise ProjectExecutionConfigurationError(
                "incomplete 3D asset staging evidence already exists"
            )

        async with self.session_factory() as session:
            record = await session.scalar(
                select(ProjectExecution).where(
                    ProjectExecution.id == execution_id,
                    ProjectExecution.status == "running",
                    ProjectExecution.lease_token == lease_token,
                    ProjectExecution.project_id == project_id,
                )
            )
            if record is None:
                raise ProjectExecutionLeaseLost(execution_id)
            artifacts = list(
                (
                    await session.scalars(
                        select(ThreeDArtifact)
                        .where(
                            ThreeDArtifact.organization_id == record.organization_id,
                            ThreeDArtifact.project_id == project_id,
                            ThreeDArtifact.status == "ready",
                            or_(
                                ThreeDArtifact.expires_at.is_(None),
                                ThreeDArtifact.expires_at > _now(),
                            ),
                        )
                        .order_by(ThreeDArtifact.created_at.desc())
                        .limit(24)
                    )
                ).all()
            )

        delivery_cap = 18 * 1024 * 1024
        per_asset_cap = 6 * 1024 * 1024
        selected: list[ThreeDArtifact] = []
        skipped_for_budget = 0
        selected_bytes = 0
        for artifact in artifacts:
            size = int(artifact.size_bytes or 0)
            if (
                size <= 0
                or size > per_asset_cap
                or selected_bytes + size > delivery_cap
                or len(selected) >= 6
            ):
                skipped_for_budget += 1
                continue
            selected.append(artifact)
            selected_bytes += size
        root.mkdir(parents=True, mode=0o700)
        assets_root = root / "assets"
        assets_root.mkdir(mode=0o700)
        rows: list[dict[str, Any]] = []
        if selected:
            store = ThreeDObjectStore()
            for index, artifact in enumerate(selected):
                maximum = min(
                    int(settings.THREE_D_MAX_OUTPUT_BYTES),
                    max(int(artifact.size_bytes or 0) + 1, 1024 * 1024),
                )
                body = await asyncio.to_thread(
                    store.get_bytes, artifact.object_key, max_bytes=maximum
                )
                digest = sha256(body).hexdigest()
                if digest != artifact.checksum or len(body) != int(artifact.size_bytes):
                    raise ProjectExecutionConfigurationError(
                        "a ready 3D artifact failed staging integrity verification"
                    )
                name = f"asset-{index+1:02d}.glb"
                destination = assets_root / name
                with destination.open("xb") as stream:
                    stream.write(body)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.chmod(destination, 0o600)
                metadata = dict(artifact.artifact_metadata or {})
                rows.append(
                    {
                        "artifact_id": artifact.id,
                        "job_id": artifact.job_id,
                        "path": f"assets/{name}",
                        "sha256": digest,
                        "size_bytes": len(body),
                        "provider": str(metadata.get("provider") or "unknown"),
                        "metadata": {
                            key: metadata.get(key)
                            for key in (
                                "mesh_count",
                                "material_count",
                                "pbr_material_count",
                                "texture_count",
                                "compression_policy",
                                "fallback_used",
                                "fallback_provider",
                                "license",
                            )
                            if key in metadata
                        },
                    }
                )
        manifest = {
            "schema_version": 1,
            "execution_id": execution_id,
            "project_id": project_id,
            "asset_count": len(rows),
            "available_asset_count": len(artifacts),
            "skipped_for_delivery_budget": skipped_for_budget,
            "delivery_asset_cap_bytes": delivery_cap,
            "per_asset_cap_bytes": per_asset_cap,
            "total_bytes": sum(item["size_bytes"] for item in rows),
            "assets": rows,
            "procedural_world_allowed_when_empty": True,
        }
        temporary = root / ".manifest.json.tmp"
        temporary.write_text(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        os.chmod(temporary, 0o600)
        os.replace(temporary, manifest_path)
        return str(manifest_path)

    async def update_stage(
        self,
        execution_id: str,
        lease_token: str,
        stage: str,
        progress: int,
    ) -> None:
        async with self.session_factory() as session:
            record = await session.scalar(
                select(ProjectExecution)
                .where(
                    ProjectExecution.id == execution_id,
                    ProjectExecution.status == "running",
                    ProjectExecution.lease_token == lease_token,
                )
                .with_for_update()
            )
            if record is None:
                raise ProjectExecutionLeaseLost(execution_id)
            record.stage = stage[:64]
            record.progress = max(record.progress, max(0, min(99, int(progress))))
            record.updated_at = self._database_timestamp(session)
            project = await session.scalar(
                select(Project).where(Project.id == record.project_id).with_for_update()
            )
            if project is not None:
                project.status = "in_progress"
                project.progress = max(project.progress, min(95, record.progress))
            await session.commit()

    async def _heartbeat(
        self,
        execution_id: str,
        lease_token: str,
        stop_event: asyncio.Event,
    ) -> None:
        interval = min(
            settings.PROJECT_EXECUTION_HEARTBEAT_SECONDS,
            max(2, settings.PROJECT_EXECUTION_JOB_LEASE_SECONDS // 3),
        )
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
            except TimeoutError:
                await self.renew(execution_id, lease_token)

    async def execute_claim(self, execution_id: str, lease_token: str) -> None:
        payload = await self.load_payload(execution_id, lease_token)
        if payload.get("execution_mode") == "3d_full":
            payload["three_d_asset_manifest"] = await self.prepare_three_d_assets(
                execution_id=execution_id,
                lease_token=lease_token,
                project_id=payload["project_id"],
            )
        stop_event = asyncio.Event()
        heartbeat_task = asyncio.create_task(
            self._heartbeat(execution_id, lease_token, stop_event)
        )
        loop = asyncio.get_running_loop()

        def stage_callback(stage: str, progress: int) -> None:
            future = asyncio.run_coroutine_threadsafe(
                self.update_stage(
                    execution_id, lease_token, stage, progress
                ),
                loop,
            )
            future.result(
                timeout=max(
                    5, settings.PROJECT_EXECUTION_HEARTBEAT_SECONDS * 2
                )
            )

        operation_task = asyncio.create_task(
            asyncio.to_thread(
                self.runner.run,
                **payload,
                stage_callback=stage_callback,
            )
        )
        try:
            done, _ = await asyncio.wait(
                {operation_task, heartbeat_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if heartbeat_task in done and not operation_task.done():
                error = heartbeat_task.exception()
                operation_task.cancel()
                await asyncio.gather(operation_task, return_exceptions=True)
                raise error or ProjectExecutionLeaseLost(execution_id)
            summary = await operation_task
            await self.complete(execution_id, lease_token, summary)
        except BaseException as exc:
            await self.fail(execution_id, lease_token, exc)
        finally:
            stop_event.set()
            heartbeat_task.cancel()
            await asyncio.gather(heartbeat_task, return_exceptions=True)

    async def complete(
        self,
        execution_id: str,
        lease_token: str,
        summary: dict[str, Any],
    ) -> None:
        async with self.session_factory() as session:
            record = await session.scalar(
                select(ProjectExecution)
                .where(
                    ProjectExecution.id == execution_id,
                    ProjectExecution.status == "running",
                    ProjectExecution.lease_token == lease_token,
                )
                .with_for_update()
            )
            if record is None:
                raise ProjectExecutionLeaseLost(execution_id)
            record.status = "completed"
            record.stage = "approved" if summary.get("approved") is True else "rework_required"
            record.progress = 100
            record.model = str(summary.get("model") or "") or None
            record.calculated_cost_usd = float(summary.get("calculated_cost") or 0.0)
            record.requests_count = int(summary.get("requests_count") or 0)
            record.retries_count = int(summary.get("retries_count") or 0)
            record.input_tokens = int(summary.get("input_tokens") or 0)
            record.output_tokens = int(summary.get("output_tokens") or 0)
            record.total_tokens = int(summary.get("total_tokens") or 0)
            record.approved = bool(summary.get("approved"))
            record.readiness_score = float(summary.get("readiness_score") or 0.0)
            record.result_summary = summary
            record.evidence_path = str(summary.get("output_directory") or "") or None
            record.error_code = None
            record.error_message = None
            record.lease_token = None
            record.completed_at = _now()
            project = await session.scalar(
                select(Project).where(Project.id == record.project_id).with_for_update()
            )
            if project is not None:
                project.status = "active" if record.approved else "planning"
                project.progress = (
                    100 if record.approved else max(project.progress, 60)
                )

            workforce = summary.get("workforce") or []
            if isinstance(workforce, list):
                for worker in workforce:
                    if not isinstance(worker, dict) or not worker.get("worker_id"):
                        continue
                    resource_id = f"{record.organization_id}:{worker['worker_id']}"
                    workforce_record = await session.scalar(
                        select(OwnerControlRecord).where(
                            OwnerControlRecord.domain == "digital-workforce",
                            OwnerControlRecord.resource_id == resource_id,
                        )
                    )
                    payload = {
                        **worker,
                        "organization_id": record.organization_id,
                        "project_id": record.project_id,
                        "execution_id": record.id,
                        "last_evaluated_at": _now().isoformat(),
                    }
                    if workforce_record is None:
                        session.add(
                            OwnerControlRecord(
                                domain="digital-workforce",
                                resource_id=resource_id,
                                status=str(worker.get("employment_state") or "active"),
                                enabled=(
                                    worker.get("employment_state")
                                    not in {"suspended", "retired"}
                                ),
                                payload=payload,
                                version=1,
                            )
                        )
                    else:
                        workforce_record.status = str(
                            worker.get("employment_state") or "active"
                        )
                        workforce_record.enabled = (
                            worker.get("employment_state")
                            not in {"suspended", "retired"}
                        )
                        workforce_record.payload = payload
                        workforce_record.version += 1
            session.add(
                Notification(
                    organization_id=record.organization_id,
                    recipient_id=record.requested_by_id,
                    type="project.execution.completed",
                    title="Full governed project cycle completed",
                    message=(
                        "The project passed through cognitive, government, research, "
                        "ministry, engineering, security, workforce and release review. "
                        + (
                            "Every retained evidence gate passed."
                            if record.approved
                            else "The release remains withheld with a truthful rework and training plan."
                        )
                    ),
                    severity="success" if record.approved else "info",
                    payload={
                        "project_id": record.project_id,
                        "execution_id": record.id,
                        "approved": record.approved,
                        "readiness_score": record.readiness_score,
                    },
                )
            )
            session.add(
                AuditEvent(
                    organization_id=record.organization_id,
                    user_id=None,
                    action="project.execution.completed",
                    resource_type="project_execution",
                    resource_id=record.id,
                    details={
                        "project_id": record.project_id,
                        "approved": record.approved,
                        "readiness_score": record.readiness_score,
                        "requests_count": record.requests_count,
                        "calculated_cost_usd": record.calculated_cost_usd,
                        "production_modified": False,
                        "phase": summary.get("phase"),
                        "all_governance_layers_executed": bool(
                            summary.get("all_governance_layers_executed")
                        ),
                        "workers_evaluated": len(
                            summary.get("workforce") or []
                        ),
                    },
                )
            )
            await session.commit()

    async def fail(
        self,
        execution_id: str,
        lease_token: str,
        exc: BaseException,
    ) -> None:
        code, message = sanitized_execution_error(exc)
        async with self.session_factory() as session:
            record = await session.scalar(
                select(ProjectExecution)
                .where(
                    ProjectExecution.id == execution_id,
                    ProjectExecution.status == "running",
                    ProjectExecution.lease_token == lease_token,
                )
                .with_for_update()
            )
            if record is None:
                return
            record.status = "failed"
            record.stage = "failed"
            record.error_code = code
            record.error_message = message
            record.lease_token = None
            record.completed_at = _now()
            project = await session.scalar(
                select(Project).where(Project.id == record.project_id).with_for_update()
            )
            if project is not None:
                project.status = "planning"
            session.add(
                Notification(
                    organization_id=record.organization_id,
                    recipient_id=record.requested_by_id,
                    type="project.execution.failed",
                    title="Full governed project cycle stopped safely",
                    message=message,
                    severity="error",
                    payload={
                        "project_id": record.project_id,
                        "execution_id": record.id,
                        "error_code": code,
                    },
                )
            )
            session.add(
                AuditEvent(
                    organization_id=record.organization_id,
                    user_id=None,
                    action="project.execution.failed",
                    resource_type="project_execution",
                    resource_id=record.id,
                    details={
                        "project_id": record.project_id,
                        "error_code": code,
                        "production_modified": False,
                    },
                )
            )
            await session.commit()
        logger.error("Project execution failed", execution_id=execution_id, error_code=code)

    async def run_once(self) -> bool:
        claim = await self.claim()
        if claim is None:
            return False
        await self.execute_claim(*claim)
        return True


async def healthcheck() -> int:
    try:
        import shutil

        ProjectPlanningRunner()
        for executable in ("node", "npm", "chromedriver"):
            if not shutil.which(executable):
                raise RuntimeError(f"project worker executable is unavailable: {executable}")
        if not (shutil.which("chromium-browser") or shutil.which("chromium")):
            raise RuntimeError("project worker Chromium runtime is unavailable")
        async with SessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return 0
    except Exception:
        logger.exception("Project worker healthcheck failed")
        return 1


async def run_worker() -> None:
    worker = ProjectExecutionWorker()
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, stop_event.set)
        except NotImplementedError:
            pass
    logger.info("Project execution worker started")
    while not stop_event.is_set():
        processed = await worker.run_once()
        if processed:
            continue
        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=settings.PROJECT_EXECUTION_WORKER_POLL_SECONDS,
            )
        except TimeoutError:
            pass
    logger.info("Project execution worker stopped")


def main() -> int:
    setup_logging()
    if "--healthcheck" in sys.argv:
        return asyncio.run(healthcheck())
    if not settings.PROJECT_EXECUTION_ENABLED:
        logger.warning("Project execution worker is disabled")
        return 0
    asyncio.run(run_worker())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
