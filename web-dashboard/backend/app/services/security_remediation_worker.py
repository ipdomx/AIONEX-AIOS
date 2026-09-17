"""Owned local remediation preparation with durable maintenance admission."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar, cast
from uuid import uuid4

from sqlalchemy import Table, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger, setup_logging
from app.db.base import SessionLocal
from app.db.models import AuditEvent, SecurityFinding, SecurityRemediation, SecurityTarget
from app.services.host_maintenance_admission import HostMaintenanceClosed, read_admission_snapshot
from app.services.host_maintenance_remediation import (
    CONSUMER,
    RemediationActivityOwnership,
    RemediationActivityOwnershipLost,
    begin_remediation_preparation,
    finish_remediation_activity,
    heartbeat_remediation_activity,
    mark_remediation_activity_unresolved,
    pristine_planned_remediation_conditions,
    register_remediation_activity,
    require_owned_remediation_activity,
    require_remediation_admission,
    settle_remediation_activity,
)
from app.services.security_remediation_files import (
    RemediationBuildInput,
    RemediationIOOutcome,
    prepare_remediation_bundle,
    validate_work_root,
)

logger = get_logger(__name__)
SOURCE_ROOT = Path("/var/lib/aionex/security-sources")
PROJECT_EXECUTION_ROOT = Path("/var/lib/aionex/project-executions")
WORK_ROOT = Path("/var/lib/aionex/security-remediations")
SessionFactory = Callable[[], AsyncSession]
RemediationBuilder = Callable[[RemediationBuildInput, threading.Event], RemediationIOOutcome]
_Result = TypeVar("_Result")
_CYCLE_COLUMNS = {
    "id", "resource_id", "consumer", "worker_incarnation", "admitted_generation",
    "ownership_nonce", "state", "phase", "job_id", "started_at", "heartbeat_at",
    "lease_expires_at", "unresolved_reason",
}


class RemediationPreparationUncertain(RuntimeError):
    """Actual work or result publication requires explicit reconciliation."""


def now() -> datetime:
    return datetime.now(UTC)


class Worker:
    def __init__(
        self,
        *,
        session_factory: SessionFactory | None = None,
        builder: RemediationBuilder | None = None,
        heartbeat_interval_seconds: float = 20.0,
    ) -> None:
        if heartbeat_interval_seconds <= 0:
            raise ValueError("Remediation heartbeat interval must be positive")
        self.session_factory = session_factory if session_factory is not None else SessionLocal
        self.builder = builder if builder is not None else prepare_remediation_bundle
        self.heartbeat_interval_seconds = heartbeat_interval_seconds
        self.worker_incarnation = str(uuid4())
        self.stop_event = asyncio.Event()
        self.cycles = 0
        self.errors = 0
        self.health = Path(os.getenv(
            "SECURITY_REMEDIATION_WORKER_HEALTH_FILE",
            "/tmp/aionex-security-remediation-worker.json",
        ))
        self.poll = max(1, int(os.getenv("SECURITY_REMEDIATION_WORKER_POLL_SECONDS", "5")))

    def write_health(self, status: str) -> None:
        """Publish excluded control-plane liveness, never preparation evidence."""
        payload = {
            "status": status,
            "checked_at": now().isoformat(),
            "checked_at_epoch": time.time(),
            "cycles": self.cycles,
            "errors": self.errors,
            "secret_returned": False,
        }
        self.health.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.health.with_name("." + self.health.name + ".tmp")
        temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.replace(temporary, self.health)

    async def preflight(self) -> None:
        """Validate prepared resources and schema without payload writes or repair."""
        validate_work_root(WORK_ROOT)
        async with self.session_factory() as session:
            ready = bool(await session.scalar(text(
                "SELECT to_regclass('security_remediations') IS NOT NULL "
                "AND to_regclass('security_findings') IS NOT NULL "
                "AND to_regclass('security_targets') IS NOT NULL "
                "AND to_regclass('host_maintenance_work_cycles') IS NOT NULL"
            )))
            if not ready:
                raise RuntimeError("Remediation worker database schema is not current")
            cycle_columns = set((await session.scalars(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema=current_schema() "
                "AND table_name='host_maintenance_work_cycles'"
            ))).all())
            remediation_columns = set((await session.scalars(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema=current_schema() "
                "AND table_name='security_remediations'"
            ))).all())
            if not _CYCLE_COLUMNS <= cycle_columns or not {
                "preparation_protocol_version", "preparation_outcome",
            } <= remediation_columns:
                raise RuntimeError("Remediation ownership schema is not current")
            # A valid CLOSED authority is ready and keeps the worker idle.
            await read_admission_snapshot(session, required_scope=CONSUMER)

    async def _await_actual(self, task: asyncio.Task[_Result]) -> _Result:
        """Repeated caller cancellation never detaches actual thread/DB cleanup."""
        while not task.done():
            try:
                await asyncio.wait_for(
                    asyncio.shield(task), timeout=min(20.0, self.heartbeat_interval_seconds)
                )
            except TimeoutError:
                try:
                    self.write_health("degraded")
                except Exception:
                    logger.error("Remediation settlement health publication failed")
            except asyncio.CancelledError:
                continue
        return task.result()

    async def _retain_uncertainty(
        self, ownership: RemediationActivityOwnership, reason: str
    ) -> None:
        marker = asyncio.create_task(mark_remediation_activity_unresolved(
            ownership, reason=reason, session_factory=self.session_factory
        ))
        try:
            await self._await_actual(marker)
        except BaseException:
            # Failure to acknowledge this update leaves the original durable row.
            logger.error("Remediation uncertainty marker was not acknowledged")

    async def claim(self) -> RemediationActivityOwnership | None:
        ownership: RemediationActivityOwnership | None = None
        try:
            async with self.session_factory() as session:
                async with session.begin():
                    await require_remediation_admission(session)
                    item = await session.scalar(
                        select(SecurityRemediation)
                        .where(*pristine_planned_remediation_conditions(
                            cast(Table, SecurityRemediation.__table__)
                        ))
                        .order_by(SecurityRemediation.created_at, SecurityRemediation.id)
                        .with_for_update(skip_locked=True)
                        .limit(1)
                    )
                    if item is not None:
                        ownership = await register_remediation_activity(
                            session,
                            remediation_id=item.id,
                            worker_incarnation=self.worker_incarnation,
                        )
        except HostMaintenanceClosed:
            return None
        except BaseException:
            if ownership is not None:
                await self._retain_uncertainty(ownership, "remediation-claim-commit-uncertain")
            raise
        return ownership

    async def _begin(self, ownership: RemediationActivityOwnership) -> None:
        async with self.session_factory() as session:
            async with session.begin():
                await begin_remediation_preparation(session, ownership)
        # A capability is usable only after the context's commit was acknowledged.

    async def _load_input(
        self, ownership: RemediationActivityOwnership
    ) -> RemediationBuildInput:
        async with self.session_factory() as session:
            async with session.begin():
                await require_owned_remediation_activity(session, ownership)
                item = await session.get(SecurityRemediation, ownership.remediation_id)
                if item is None:
                    raise RemediationActivityOwnershipLost("Remediation job is unavailable")
                finding = await session.get(SecurityFinding, item.finding_id)
                target = await session.get(SecurityTarget, finding.target_id) if finding else None
                if (
                    finding is None or target is None
                    or target.project_id != item.project_id
                    or target.organization_id != item.organization_id
                    or finding.organization_id != item.organization_id
                ):
                    raise ValueError("Remediation source target is invalid")
                metadata = target.target_metadata
                raw = metadata.get("source_snapshot") if isinstance(metadata, dict) else None
                if not isinstance(raw, str) or not raw.strip():
                    raise ValueError("Remediation target source snapshot is unavailable")
                plan_json = (
                    json.dumps(item.plan, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
                ).encode("utf-8")
                return RemediationBuildInput(
                    remediation_id=item.id,
                    activity_id=ownership.activity_id,
                    source=Path(raw.strip()),
                    allowed_roots=(SOURCE_ROOT, PROJECT_EXECUTION_ROOT),
                    work_root=WORK_ROOT,
                    plan_json=plan_json,
                )

    async def _commit_outcome(
        self, ownership: RemediationActivityOwnership, outcome: RemediationIOOutcome
    ) -> None:
        if outcome.unresolved_reason is not None:
            raise RemediationPreparationUncertain("Remediation filesystem did not settle")
        async with self.session_factory() as session:
            async with session.begin():
                await require_owned_remediation_activity(session, ownership)
                item = await session.get(SecurityRemediation, ownership.remediation_id)
                if item is None:
                    raise RemediationActivityOwnershipLost("Remediation job is unavailable")
                if outcome.evidence is not None:
                    item.status = "worktree_ready"
                    item.worktree_ref = f"security-remediation://{item.id}/source"
                    item.regression_result = {
                        "isolation": dict(outcome.evidence), "production_modified": False,
                    }
                    phase = "prepared"
                    action = "security.remediation.worktree_ready"
                    details = {**outcome.evidence, "production_modified": False}
                elif outcome.error_type:
                    item.status = "failed"
                    item.worktree_ref = None
                    item.regression_result = {
                        "error_type": outcome.error_type, "production_modified": False,
                    }
                    phase = "clean_failed"
                    action = "security.remediation.failed"
                    details = dict(item.regression_result)
                else:
                    raise RemediationPreparationUncertain("Remediation outcome is invalid")
                session.add(AuditEvent(
                    organization_id=item.organization_id,
                    user_id=item.requested_by_id,
                    action=action,
                    resource_type="security_remediation",
                    resource_id=item.id,
                    details=details,
                ))
                await session.flush()
                await settle_remediation_activity(session, ownership, outcome=phase)

    async def _operate(
        self, ownership: RemediationActivityOwnership, stop: threading.Event
    ) -> None:
        try:
            build_input = await self._load_input(ownership)
        except ValueError as exc:
            outcome = RemediationIOOutcome(error_type=type(exc).__name__)
        else:
            # This task is never cancelled by the supervisor. Its thread remains
            # joined through publication and cleanup, including repeated cancellation.
            outcome = await asyncio.to_thread(self.builder, build_input, stop)
        if outcome.unresolved_reason is not None:
            raise RemediationPreparationUncertain("Remediation I/O requires reconciliation")
        await self._commit_outcome(ownership, outcome)

    async def _heartbeat(
        self, ownership: RemediationActivityOwnership, stopped: asyncio.Event
    ) -> None:
        while not stopped.is_set():
            await heartbeat_remediation_activity(
                ownership, session_factory=self.session_factory
            )
            self.write_health("healthy")
            try:
                await asyncio.wait_for(stopped.wait(), timeout=self.heartbeat_interval_seconds)
            except TimeoutError:
                continue

    async def prepare(self, ownership: RemediationActivityOwnership) -> None:
        try:
            await self._begin(ownership)
        except RemediationActivityOwnershipLost:
            # A replay must not poison the legitimate concurrent owner's row.
            raise
        except BaseException:
            await self._retain_uncertainty(ownership, "remediation-begin-commit-uncertain")
            raise
        stop = threading.Event()
        heartbeat_stopped = asyncio.Event()
        operation = asyncio.create_task(self._operate(ownership, stop))
        heartbeat = asyncio.create_task(self._heartbeat(ownership, heartbeat_stopped))
        try:
            done, _ = await asyncio.wait(
                {operation, heartbeat}, return_when=asyncio.FIRST_COMPLETED
            )
            if heartbeat in done:
                await heartbeat
                if not operation.done():
                    raise RemediationPreparationUncertain("Remediation heartbeat stopped early")
            await asyncio.shield(operation)
            heartbeat_stopped.set()
            await asyncio.shield(heartbeat)
            await finish_remediation_activity(
                ownership, session_factory=self.session_factory
            )
        except BaseException:
            stop.set()
            heartbeat_failed = heartbeat.done() and (
                heartbeat.cancelled() or heartbeat.exception() is not None
            )
            if heartbeat_failed:
                await self._retain_uncertainty(ownership, "remediation-heartbeat-unresolved")
            # Caller cancellation leaves the active durable row as a blocker and
            # keeps its heartbeat alive until actual copying/cleanup/result commit
            # settles. Observe later heartbeat loss during that same join.
            while not operation.done() and not heartbeat_failed:
                try:
                    done, _ = await asyncio.wait(
                        {operation, heartbeat},
                        timeout=min(20.0, self.heartbeat_interval_seconds),
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                except asyncio.CancelledError:
                    continue
                if heartbeat in done:
                    heartbeat_failed = True
                    await self._retain_uncertainty(ownership, "remediation-heartbeat-unresolved")
                elif not done:
                    try:
                        self.write_health("degraded")
                    except Exception:
                        logger.error("Remediation settlement health publication failed")
            # Never cancel the task wrapping to_thread, including repeated cancel.
            try:
                await self._await_actual(operation)
            except BaseException:
                logger.debug("Remediation unsettled operation completed with an error")
            heartbeat_stopped.set()
            try:
                await self._await_actual(heartbeat)
            except BaseException:
                logger.debug("Remediation unsettled heartbeat completed with an error")
            if not heartbeat_failed:
                await self._retain_uncertainty(ownership, "remediation-operation-unresolved")
            raise

    async def run_once(self) -> int:
        if self.stop_event.is_set():
            return 0
        ownership = await self.claim()
        if ownership is None:
            self.write_health("healthy")
            return 0
        await self.prepare(ownership)
        self.write_health("healthy")
        return 1

    async def run(self) -> None:
        await self.preflight()
        self.write_health("healthy")
        while not self.stop_event.is_set():
            self.cycles += 1
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.errors += 1
                logger.error("Security remediation worker cycle failed", error_type=type(exc).__name__)
                self.write_health("degraded")
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=self.poll)
            except TimeoutError:
                continue

    def stop(self) -> None:
        """Gracefully finish the admitted activity before declining new claims."""
        self.stop_event.set()


def healthcheck() -> int:
    path = Path(os.getenv(
        "SECURITY_REMEDIATION_WORKER_HEALTH_FILE",
        "/tmp/aionex-security-remediation-worker.json",
    ))
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        age = time.time() - float(data["checked_at_epoch"])
        return 0 if data.get("status") == "healthy" and 0 <= age < 90 else 1
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return 1


async def _main() -> None:
    setup_logging()
    worker = Worker()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, worker.stop)
        except NotImplementedError:
            logger.debug("Signal handlers are unavailable on this runtime", signal=int(sig))
    await worker.run()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--healthcheck", action="store_true")
    args = parser.parse_args()
    if args.healthcheck:
        raise SystemExit(healthcheck())
    asyncio.run(_main())
