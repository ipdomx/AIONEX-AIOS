"""Durable single-server worker for real project planning executions."""

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
    Project,
    ProjectExecution,
)
from app.services.project_execution import (
    ProjectPlanningRunner,
    sanitized_execution_error,
)
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
            record.stage = "provider_execution"
            record.progress = max(record.progress, 20)
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
                "project_name": project_name,
                "objective": record.objective,
            }

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
        stop_event = asyncio.Event()
        heartbeat_task = asyncio.create_task(
            self._heartbeat(execution_id, lease_token, stop_event)
        )
        operation_task = asyncio.create_task(asyncio.to_thread(self.runner.run, **payload))
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
                project.status = "active"
                project.progress = max(project.progress, 25)
            session.add(
                Notification(
                    organization_id=record.organization_id,
                    recipient_id=record.requested_by_id,
                    type="project.execution.completed",
                    title="AI project planning cycle completed",
                    message=(
                        "The six-department planning cycle finished. "
                        + (
                            "All review gates passed."
                            if record.approved
                            else "The result includes a truthful rework plan before implementation approval."
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
                    title="AI project planning cycle stopped safely",
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
        ProjectPlanningRunner()
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
