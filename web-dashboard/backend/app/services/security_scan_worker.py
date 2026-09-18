"""One-shot Security Lab worker with durable ownership and joined supervision.

Cancellation is intent, not settlement. Resources, operation and heartbeat have
separate persisted completion evidence. Unknown observations remain blockers;
there is no expiry-based takeover, automatic replay, or host-closure attestation.
"""

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

from sqlalchemy import cast, func, select
from sqlalchemy.dialects.postgresql import JSONB

from app.core.logging import get_logger, setup_logging
from app.db.base import SessionLocal
from app.db.models import AuditEvent, OwnerControlRecord, SecurityScan, SecurityScanExecution, uuid_str
from app.services import security_tools
from app.services.host_maintenance_admission import HostMaintenanceClosed, SessionFactory
from app.services import host_maintenance_scan_execution as executions
from app.services.security_scan_resources import ScanResourceRuntime, finish, join_task
from app.services.host_maintenance_scan_admission import require_scan_admission
from app.services.security_fabric import get_policy
from app.services.security_scanning import execute_scan

logger = get_logger(__name__)
GUARD_KEY = "_execution_guard"
GUARD_PROTOCOL = 1
_PHASES = frozenset({"claimed", "executing", "returned", "unresolved"})


def now() -> datetime:
    return datetime.now(UTC)


def _execution_phase(scan: SecurityScan) -> str | None:
    """Only an exact server-written guard can authorize a one-time start."""
    if not isinstance(scan.summary, dict):
        return None
    guard = scan.summary.get(GUARD_KEY)
    if (
        not isinstance(guard, dict)
        or set(guard) != {"protocol_version", "phase", "cleanup_verified"}
        or type(guard["protocol_version"]) is not int
        or guard["protocol_version"] != GUARD_PROTOCOL
        or not isinstance(guard["phase"], str)
        or guard["phase"] not in _PHASES
        or guard["cleanup_verified"] is not False
    ):
        return None
    return guard["phase"]


def _set_execution_phase(scan: SecurityScan, phase: str) -> None:
    if phase not in _PHASES or not isinstance(scan.summary, dict):
        raise ValueError("Invalid execution guard transition")
    scan.summary = {
        **scan.summary,
        GUARD_KEY: {
            "protocol_version": GUARD_PROTOCOL,
            "phase": phase,
            # This part intentionally does not attest process/thread/ZAP cleanup.
            "cleanup_verified": False,
        },
    }


class SecurityScanWorker:
    def __init__(self, *, session_factory: SessionFactory | None = None) -> None:
        self._session_factory = session_factory
        self.incarnation = str(uuid4())
        self.heartbeat_seconds = 5.0
        self.stop_event = asyncio.Event()
        self.health_path = Path(
            os.getenv(
                "SECURITY_SCAN_WORKER_HEALTH_FILE",
                "/tmp/aionex-security-scan-worker.json",
            )
        )
        self.poll_seconds = max(
            1, int(os.getenv("SECURITY_SCAN_WORKER_POLL_SECONDS", "5"))
        )
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
        tmp = self.health_path.with_name("." + self.health_path.name + ".tmp")
        tmp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.health_path)

    async def preflight(self) -> None:
        async with self.sessions() as session:
            await session.execute(select(SecurityScan.id).limit(1))
            tools = security_tools.catalog_snapshot()
            available_ids = sorted(item["id"] for item in tools if item["available"])
            record = await session.scalar(
                select(OwnerControlRecord)
                .where(
                    OwnerControlRecord.domain == "security-tools-runtime",
                    OwnerControlRecord.resource_id == "default",
                )
                .with_for_update()
            )
            payload = {
                "available_ids": available_ids,
                "checked_at": now().isoformat(),
                "worker": "security-scan-worker",
                "catalog_size": len(tools),
            }
            if record is None:
                record = OwnerControlRecord(
                    id=uuid_str(),
                    domain="security-tools-runtime",
                    resource_id="default",
                    status="active",
                    enabled=True,
                    payload=payload,
                    version=1,
                )
                session.add(record)
            else:
                record.status = "active"
                record.enabled = True
                record.payload = payload
                record.version += 1
            await session.commit()

    async def claim(self) -> tuple[str, str] | None:
        """Atomically register untouched backlog; never adopt or replay old work."""
        async with self.sessions() as session:
            await require_scan_admission(session)
            summary = cast(SecurityScan.summary, JSONB)
            scan = await session.scalar(
                select(SecurityScan).where(
                    SecurityScan.status == "queued", SecurityScan.attempts == 0,
                    SecurityScan.max_attempts > 0, SecurityScan.started_at.is_(None),
                    SecurityScan.completed_at.is_(None), SecurityScan.cancelled_at.is_(None),
                    SecurityScan.lease_token.is_(None), SecurityScan.error_code.is_(None),
                    SecurityScan.error_message.is_(None),
                    func.jsonb_typeof(summary) == "object",
                    ~func.jsonb_exists(summary, GUARD_KEY),
                    ~func.jsonb_exists(summary, "cancellation_before_claim"),
                    ~func.jsonb_exists(summary, "execution_cleanup"),
                    ~select(SecurityScanExecution.id).where(
                        SecurityScanExecution.scan_id == SecurityScan.id,
                    ).exists(),
                ).order_by(SecurityScan.created_at, SecurityScan.id)
                .with_for_update(skip_locked=True).limit(1)
            )
            if scan is None:
                return None
            owner = await executions.register_execution(
                session, scan_id=scan.id, worker_incarnation=self.incarnation,
            )
            session.add(AuditEvent(
                organization_id=scan.organization_id, user_id=scan.requested_by_id,
                action="security.scan.claimed", resource_type="security_scan",
                resource_id=scan.id, details={"attempt": 1, "reclaimed": False},
            ))
            await session.commit()
            return scan.id, owner.ownership_nonce

    async def _owner(self, scan_id: str, nonce: str) -> executions.ScanExecutionOwnership | None:
        async with self.sessions() as session:
            return await executions.find_execution(session, scan_id, nonce, self.incarnation)

    async def _begin_execution(self, scan_id: str, nonce: str) -> bool:
        async with self.sessions() as session:
            owner = await executions.find_execution(session, scan_id, nonce, self.incarnation)
            if owner is None:
                return False
            started = await executions.begin_execution(session, owner)
            if started:
                await session.commit()
            return started

    async def _mark_unresolved(self, scan_id: str, nonce: str, error_type: str) -> None:
        owner = await self._owner(scan_id, nonce)
        if owner is None:
            return
        async with self.sessions() as session, session.begin():
            scan = await session.scalar(select(SecurityScan).where(
                SecurityScan.id == scan_id,
            ).with_for_update())
            row = await executions.locked_execution(session, owner)
            if row.state == "settled":
                return
            row.state = "unresolved"
            row.unresolved_reason = error_type[:160]
            if scan is not None and scan.status == "running" and scan.lease_token == nonce:
                _set_execution_phase(scan, "unresolved")
                scan.error_code = "SECURITY_SCAN_RECONCILIATION_REQUIRED"
                scan.error_message = error_type[:160]
                scan.completed_at = None

    async def _abandon_unstarted(
        self, owner: executions.ScanExecutionOwnership, error: BaseException,
    ) -> None:
        """No I/O was dispatched; an ambiguous begin commit is NEVER adopted."""
        async with self.sessions() as session, session.begin():
            scan = await session.scalar(select(SecurityScan).where(
                SecurityScan.id == owner.scan_id,
            ).with_for_update())
            row = await executions.locked_execution(session, owner)
            if row.phase != "claimed" or row.resources or row.state == "settled":
                # The begin may have committed without its acknowledgement.
                # Preserve that fence rather than inventing a no-start proof.
                return
            if scan is None or scan.status != "running" or scan.lease_token != owner.ownership_nonce:
                raise executions.ScanExecutionOwnershipLost("Unstarted claim no longer matches")
            row.phase = "returned"
            row.outcome = "cancelled" if isinstance(error, asyncio.CancelledError) else "failed"
            row.operation_stopped_at = await executions._now(session)
            row.supervisor_stopped_at = row.operation_stopped_at  # no supervisor was created
            row.unresolved_reason = type(error).__name__
            _set_execution_phase(scan, "returned")
        await executions.reconcile_returned_execution(owner.scan_id, session_factory=self.sessions)

    async def _operate(
        self, runtime: ScanResourceRuntime,
    ) -> None:
        owner = runtime.owner
        async with self.sessions() as session:
            # Never hold the business-row lock across scanner I/O. Cancellation
            # takes scan->execution locks in a separate short transaction.
            scan = await session.scalar(select(SecurityScan).where(
                SecurityScan.id == owner.scan_id, SecurityScan.status == "running",
                SecurityScan.lease_token == owner.ownership_nonce,
            ))
            if scan is None or _execution_phase(scan) != "executing":
                raise executions.ScanExecutionOwnershipLost("Business execution changed")
            with runtime.bind():
                dispatch = await runtime.reserve("async_io", "worker-dispatch")
                await runtime.update(dispatch, state="active")
                try:
                    await execute_scan(session, scan)
                finally:
                    if runtime.entered:
                        await finish(runtime.update(dispatch, state="settled", evidence={
                            "joined": True, "cleanup_complete": True,
                        }))
                    else:
                        await finish(runtime.uncertain(dispatch, executions.ScanExecutionUncertain(
                            "Executor did not enter the owned resource runtime",
                        )))
                if not runtime.entered or runtime.supervision_failed:
                    raise executions.ScanExecutionUncertain("Executor supervision is unverified")
                if runtime.cancel_requested:
                    raise executions.ScanExecutionCancelled()
                # Serialise final completion with cancellation using the same
                # lock order. The executor's results and operation-return proof
                # become durable in ONE transaction, never in separate commits.
                with session.no_autoflush:
                    await session.execute(select(SecurityScan.id).where(
                        SecurityScan.id == owner.scan_id,
                    ).with_for_update())
                    row = await executions.locked_execution(session, owner)
                if row.cancel_requested_at is not None:
                    raise executions.ScanExecutionCancelled()
                if scan.status != "completed" or scan.lease_token is not None:
                    raise executions.ScanExecutionUncertain("Executor did not produce a terminal result")
                _set_execution_phase(scan, "returned")
                await executions.operation_returned(session, owner, outcome="completed")
                await session.commit()

    async def _supervise_execution(
        self, runtime: ScanResourceRuntime, operation: asyncio.Task[None], ended: asyncio.Event,
    ) -> None:
        cancellation_sent = False
        while not ended.is_set():
            try:
                requested = await executions.heartbeat_execution(
                    runtime.owner, session_factory=self.sessions,
                )
                if requested or self.stop_event.is_set():
                    runtime.cancel_requested = True
                    if not operation.done() and not cancellation_sent:
                        operation.cancel()
                        cancellation_sent = True
                self.write_health("healthy")
            except Exception:
                runtime.supervision_failed = True
                if not operation.done() and not cancellation_sent:
                    operation.cancel()
                return
            try:
                await asyncio.wait_for(ended.wait(), timeout=self.heartbeat_seconds)
            except TimeoutError:
                pass

    async def _finalize_execution(
        self, runtime: ScanResourceRuntime, supervisor: asyncio.Task[None],
        ended: asyncio.Event, error: BaseException | None,
    ) -> None:
        # The caller already joined the real operation. Stop and join heartbeat
        # separately, before recording its proof or reconciling anything.
        ended.set()
        await supervisor
        if error is not None:
            async with self.sessions() as session, session.begin():
                scan = await session.scalar(select(SecurityScan).where(
                    SecurityScan.id == runtime.owner.scan_id,
                ).with_for_update())
                row = await executions.locked_execution(session, runtime.owner)
                if row.phase == "executing":
                    outcome = "cancelled" if isinstance(error, asyncio.CancelledError) else "failed"
                    await executions.operation_returned(session, runtime.owner, outcome=outcome)
                    if scan is not None and scan.status == "running":
                        _set_execution_phase(scan, "unresolved")
                        scan.error_code = "SECURITY_SCAN_RECONCILIATION_REQUIRED"
                        scan.error_message = type(error).__name__
                # A previously committed completed result may have lost its ACK.
                # Keep its stored proof; never overwrite it with a guessed error.
        await executions.supervisor_returned(runtime.owner, session_factory=self.sessions)
        await executions.reconcile_returned_execution(runtime.owner.scan_id, session_factory=self.sessions)

    async def run_claim(self, scan_id: str, nonce: str) -> None:
        owner = await self._owner(scan_id, nonce)
        if owner is None:
            return
        try:
            if not await self._begin_execution(scan_id, nonce):
                return
        except BaseException as exc:
            if isinstance(exc, executions.ScanExecutionCancelled):
                await finish(self._abandon_unstarted(owner, exc))
                return
            raise
        runtime = ScanResourceRuntime(owner, session_factory=self.sessions)
        # Policy reads are part of the joined task too; a failure cannot strand
        # an unrecorded background task. No resource or scan-row lock is held here.
        async def operation_body() -> None:
            async with self.sessions() as session:
                policy = await get_policy(session)
                timeout_seconds = max(60, min(int(policy.get("max_scan_runtime_seconds", 1800)), 7200))
            async with asyncio.timeout(timeout_seconds):
                await self._operate(runtime)
        operation = asyncio.create_task(operation_body())
        ended = asyncio.Event()
        supervisor = asyncio.create_task(self._supervise_execution(runtime, operation, ended))
        error: BaseException | None = None
        externally_cancelled = False
        try:
            await asyncio.shield(operation)
        except BaseException as exc:
            error = exc
            task = asyncio.current_task()
            externally_cancelled = isinstance(exc, asyncio.CancelledError) and bool(task and task.cancelling())
            if not operation.done():
                runtime.cancel_requested = True
                operation.cancel()
            try:
                await join_task(operation)
            except BaseException:
                pass  # Original failure is retained; operation is now joined.
        finalizer = asyncio.create_task(self._finalize_execution(runtime, supervisor, ended, error))
        try:
            _, interrupted = await join_task(finalizer)
            externally_cancelled = externally_cancelled or interrupted
        except BaseException:
            # The durable phase/resources remain blockers if a proof commit fails.
            logger.exception("Security scan settlement recording failed")
            raise
        if externally_cancelled:
            raise asyncio.CancelledError()
        if isinstance(error, asyncio.CancelledError) and runtime.cancel_requested:
            return  # An accepted user/shutdown cancellation must not kill the worker.
        if error is not None:
            raise error

    async def run(self) -> None:
        await self.preflight()
        self.write_health("healthy")
        while not self.stop_event.is_set():
            self.cycles += 1
            try:
                claim = await self.claim()
                if claim:
                    await self.run_claim(*claim)
                self.write_health("healthy")
            except HostMaintenanceClosed:
                self.write_health("healthy")
            except Exception:
                self.errors += 1
                logger.exception("Security scan worker cycle failed")
                self.write_health("degraded")
            try:
                await asyncio.wait_for(
                    self.stop_event.wait(), timeout=self.poll_seconds
                )
            except TimeoutError:
                continue

    def stop(self) -> None:
        self.stop_event.set()


def healthcheck() -> int:
    path = Path(
        os.getenv(
            "SECURITY_SCAN_WORKER_HEALTH_FILE", "/tmp/aionex-security-scan-worker.json"
        )
    )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        age = time.time() - float(data["checked_at_epoch"])
        return 0 if data.get("status") in {"healthy", "degraded"} and age < 90 else 1
    except Exception:
        return 1


async def _main() -> None:
    setup_logging()
    worker = SecurityScanWorker()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
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
