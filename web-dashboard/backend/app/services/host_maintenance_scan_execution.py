"""Permanent, fail-closed ownership of Security Lab execution and its resources.

Intent is committed before I/O. Expiry is only an observation: it cannot release
an execution or a ZAP engine, transfer ownership, or retry a business request.
Resource settlement and business completion are different facts. Reconciliation
only consumes already-persisted join evidence; it never manufactures that proof.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import SessionLocal
from app.db.models import AuditEvent, SecurityScan, SecurityScanExecution
from app.services.host_maintenance_admission import SessionFactory, read_admission_snapshot
from app.services.host_maintenance_scan_admission import require_scan_admission

CONSUMER = "security_scan_execution"
LEASE_SECONDS = 120
_RESOURCE_KINDS = frozenset({"thread", "process", "async_io", "zap"})
_RESOURCE_STATES = frozenset({"reserved", "active", "unresolved", "settled"})
_IDENTITY_KEYS = frozenset({
    "pid", "pgid", "sid", "start_ticks", "boot_id", "operation", "engine",
    "spider_ids", "active_ids", "submission_pending", "session_started",
})
_EVIDENCE_KEYS = frozenset({
    "joined", "group_empty", "leader_reaped", "cleanup_complete", "remote_zero",
    "not_started", "error_type",
})


class ScanExecutionOwnershipLost(RuntimeError):
    """Exact durable ownership no longer permits the operation."""


class ScanExecutionUncertain(RuntimeError):
    """Resources cannot be certified stopped/cleaned; durable evidence remains."""


class ScanExecutionCancelled(asyncio.CancelledError):
    """An admitted cancellation prevents new I/O, not proof of existing cleanup."""


@dataclass(frozen=True, slots=True)
class ScanExecutionOwnership:
    execution_id: str
    scan_id: str
    worker_incarnation: str
    admitted_generation: int
    ownership_nonce: str = field(repr=False)


def _uuid(value: Any) -> bool:
    try:
        return isinstance(value, str) and str(UUID(value)) == value
    except ValueError:
        return False


def _aware(value: Any) -> bool:
    return isinstance(value, datetime) and value.utcoffset() is not None


def _metadata(value: Any, allowed: frozenset[str]) -> bool:
    if not isinstance(value, dict) or not set(value) <= allowed:
        return False
    for item in value.values():
        if type(item) in (bool, int):
            continue
        if isinstance(item, str) and 0 < len(item) <= 160 and "\x00" not in item:
            continue
        if isinstance(item, list) and len(item) <= 64 and all(
            isinstance(x, str) and x.isascii() and x.isdecimal() and len(x) <= 19
            for x in item
        ):
            continue
        return False
    return True


def _resources(row: SecurityScanExecution) -> dict[str, dict[str, Any]]:
    data = row.resources
    if not isinstance(data, dict) or len(data) > 512:
        raise ScanExecutionUncertain("Execution resource inventory is malformed")
    for key, value in data.items():
        if not _uuid(key) or not isinstance(value, dict) or set(value) != {
            "kind", "state", "identity", "evidence",
        }:
            raise ScanExecutionUncertain("Execution resource record is malformed")
        if (not isinstance(value["kind"], str) or value["kind"] not in _RESOURCE_KINDS
                or not isinstance(value["state"], str) or value["state"] not in _RESOURCE_STATES
                or not _metadata(value["identity"], _IDENTITY_KEYS)
                or not _metadata(value["evidence"], _EVIDENCE_KEYS)):
            raise ScanExecutionUncertain("Execution resource proof is malformed")
        if value["state"] == "settled" and not _settlement_valid(value["kind"], value["evidence"]):
            raise ScanExecutionUncertain("Execution resource settlement is unsupported")
    return data


def _settlement_valid(kind: str, evidence: dict[str, Any]) -> bool:
    if evidence.get("not_started") is True:
        return evidence.get("cleanup_complete") is True
    if kind in {"thread", "async_io"}:
        return evidence.get("joined") is True and evidence.get("cleanup_complete") is True
    if kind == "process":
        return all(evidence.get(k) is True for k in (
            "leader_reaped", "group_empty", "cleanup_complete",
        ))
    if kind == "zap":
        return evidence.get("remote_zero") is True and evidence.get("cleanup_complete") is True
    return False


def _ownership(row: SecurityScanExecution) -> ScanExecutionOwnership:
    if (not all(_uuid(v) for v in (row.id, row.scan_id, row.worker_incarnation, row.ownership_nonce))
            or type(row.admitted_generation) is not int or row.admitted_generation < 1
            or not isinstance(row.state, str) or row.state not in {"active", "unresolved", "settled"}
            or not isinstance(row.phase, str) or row.phase not in {"claimed", "executing", "returned"}
            or not all(_aware(v) for v in (row.started_at, row.heartbeat_at, row.lease_expires_at))
            or row.lease_expires_at < row.heartbeat_at):
        raise ScanExecutionUncertain("Execution ownership is malformed")
    _resources(row)
    return ScanExecutionOwnership(
        row.id, row.scan_id, row.worker_incarnation, row.admitted_generation,
        row.ownership_nonce,
    )


async def _now(session: AsyncSession) -> datetime:
    if session.get_bind().dialect.name != "postgresql":
        raise ScanExecutionUncertain("Execution ownership requires PostgreSQL")
    result = await session.scalar(select(func.clock_timestamp()))
    if not _aware(result):
        raise ScanExecutionUncertain("Execution database clock is unavailable")
    return cast(datetime, result)


async def locked_execution(
    session: AsyncSession, owner: ScanExecutionOwnership,
) -> SecurityScanExecution:
    with session.no_autoflush:
        row = await session.scalar(select(SecurityScanExecution).where(
            SecurityScanExecution.id == owner.execution_id,
            SecurityScanExecution.scan_id == owner.scan_id,
            SecurityScanExecution.worker_incarnation == owner.worker_incarnation,
            SecurityScanExecution.admitted_generation == owner.admitted_generation,
            SecurityScanExecution.ownership_nonce == owner.ownership_nonce,
        ).with_for_update())
    if row is None or _ownership(row) != owner:
        raise ScanExecutionOwnershipLost("Execution ownership does not match")
    return row


async def register_execution(
    session: AsyncSession, *, scan_id: str, worker_incarnation: str,
) -> ScanExecutionOwnership:
    """Atomically claim pristine backlog and register ownership in the caller TX.

    Running/legacy work cannot be adopted after the fact. No capability can be
    used for I/O until the caller's commit has actually been acknowledged.
    """
    authority = await require_scan_admission(session)
    if not _uuid(worker_incarnation) or not _uuid(scan_id):
        raise ValueError("Execution registration identity is invalid")
    with session.no_autoflush:
        scan = await session.scalar(select(SecurityScan).where(
            SecurityScan.id == scan_id,
        ).with_for_update().execution_options(populate_existing=True))
    if scan is None or not _pristine_unowned(scan):
        raise ScanExecutionOwnershipLost("Only untouched backlog can register execution")
    existing = await session.scalar(select(SecurityScanExecution.id).where(
        SecurityScanExecution.scan_id == scan_id,
    ))
    if existing is not None:
        raise ScanExecutionOwnershipLost("Prior execution evidence prevents a fresh claim")
    stamp = await _now(session)
    nonce = str(uuid4())
    scan.status = "running"
    scan.attempts = 1
    scan.lease_token = nonce
    scan.started_at = stamp
    scan.summary = {**scan.summary, "_execution_guard": {
        "protocol_version": 1, "phase": "claimed", "cleanup_verified": False,
    }}
    row = SecurityScanExecution(
        id=str(uuid4()), scan_id=scan.id, worker_incarnation=worker_incarnation,
        admitted_generation=authority.generation, ownership_nonce=nonce,
        state="active", phase="claimed", resources={}, started_at=stamp,
        heartbeat_at=stamp, lease_expires_at=stamp + timedelta(seconds=LEASE_SECONDS),
    )
    session.add(row)
    await session.flush()
    return _ownership(row)


async def find_execution(
    session: AsyncSession, scan_id: str, nonce: str, worker_incarnation: str,
) -> ScanExecutionOwnership | None:
    row = await session.scalar(select(SecurityScanExecution).where(
        SecurityScanExecution.scan_id == scan_id,
        SecurityScanExecution.ownership_nonce == nonce,
        SecurityScanExecution.worker_incarnation == worker_incarnation,
    ))
    return _ownership(row) if row is not None else None


async def begin_execution(session: AsyncSession, owner: ScanExecutionOwnership) -> bool:
    authority = await require_scan_admission(session)
    with session.no_autoflush:
        scan = await session.scalar(select(SecurityScan).where(
            SecurityScan.id == owner.scan_id,
        ).with_for_update().execution_options(populate_existing=True))
    row = await locked_execution(session, owner)
    if (row.state != "active" or row.phase != "claimed"
            or row.admitted_generation != authority.generation):
        return False
    if row.cancel_requested_at is not None:
        raise ScanExecutionCancelled()
    guard = scan.summary.get("_execution_guard") if scan is not None and isinstance(scan.summary, dict) else None
    if (scan is None or scan.status != "running" or scan.attempts != 1
            or scan.lease_token != owner.ownership_nonce or not isinstance(guard, dict)
            or set(guard) != {"protocol_version", "phase", "cleanup_verified"}
            or type(guard["protocol_version"]) is not int or guard["protocol_version"] != 1
            or guard["phase"] != "claimed" or guard["cleanup_verified"] is not False):
        raise ScanExecutionOwnershipLost("Business scan no longer permits execution")
    if row.resources or row.operation_stopped_at is not None:
        raise ScanExecutionUncertain("Claimed execution has unexpected prior work")
    row.phase = "executing"
    scan.summary = {**scan.summary, "_execution_guard": {**guard, "phase": "executing"}}
    return True


async def reserve_resource(
    owner: ScanExecutionOwnership, kind: str, *, identity: dict[str, Any] | None = None,
    exclusive_key: str | None = None, session_factory: SessionFactory = SessionLocal,
) -> str:
    identity = dict(identity or {})
    if not isinstance(kind, str) or kind not in _RESOURCE_KINDS or not _metadata(identity, _IDENTITY_KEYS):
        raise ValueError("Resource intent is invalid")
    if kind == "zap" and exclusive_key is None:
        raise ValueError("Remote engine ownership requires an exclusive identity")
    if exclusive_key is not None and (
        kind != "zap" or not isinstance(exclusive_key, str) or len(exclusive_key) != 64
        or any(c not in "0123456789abcdef" for c in exclusive_key)
    ):
        raise ValueError("Exclusive engine identity is invalid")
    identifier = str(uuid4())
    async with session_factory() as session, session.begin():
        row = await locked_execution(session, owner)
        if row.state != "active" or row.phase != "executing":
            raise ScanExecutionOwnershipLost("Execution no longer permits new resources")
        if row.cancel_requested_at is not None:
            raise ScanExecutionCancelled()
        if len(row.resources) >= 512:
            raise ScanExecutionUncertain("Execution resource limit reached")
        if exclusive_key is not None:
            if row.zap_owner_key is not None:
                raise ScanExecutionUncertain("Execution already owns an unfinished engine")
            row.zap_owner_key = exclusive_key
        row.resources = {**row.resources, identifier: {
            "kind": kind, "state": "reserved", "identity": identity, "evidence": {},
        }}
    return identifier


async def update_resource(
    owner: ScanExecutionOwnership, identifier: str, *, state: str,
    identity: dict[str, Any] | None = None, evidence: dict[str, Any] | None = None,
    session_factory: SessionFactory = SessionLocal,
) -> None:
    if not isinstance(state, str) or state not in {"active", "unresolved", "settled"}:
        raise ValueError("Resource transition is invalid")
    if identity is not None and not _metadata(identity, _IDENTITY_KEYS):
        raise ValueError("Resource identity is invalid")
    if evidence is not None and not _metadata(evidence, _EVIDENCE_KEYS):
        raise ValueError("Resource evidence is invalid")
    async with session_factory() as session, session.begin():
        row = await locked_execution(session, owner)
        resources = _resources(row)
        if row.state == "settled" or row.phase != "executing" or identifier not in resources:
            raise ScanExecutionOwnershipLost("Resource no longer belongs to active execution")
        old = resources[identifier]
        if old["state"] == "settled" or (old["state"] == "unresolved" and state == "active"):
            raise ScanExecutionOwnershipLost("Resource transition would erase prior proof")
        item = {**old, "state": state}
        if identity is not None:
            item["identity"] = {**old["identity"], **identity}
        if evidence is not None:
            item["evidence"] = dict(evidence)
        if state == "settled" and item["evidence"].get("not_started") is True and old["state"] != "reserved":
            raise ScanExecutionUncertain("Started resource cannot be reclassified as never started")
        if state == "settled" and not _settlement_valid(item["kind"], item["evidence"]):
            raise ScanExecutionUncertain("Resource settlement lacks required proof")
        if state == "settled" and item["kind"] == "zap":
            if item["identity"].get("submission_pending") is True:
                raise ScanExecutionUncertain("An engine submission is still uncertain")
            row.zap_owner_key = None
        row.resources = {**resources, identifier: item}


async def heartbeat_execution(
    owner: ScanExecutionOwnership, *, session_factory: SessionFactory = SessionLocal,
) -> bool:
    async with session_factory() as session, session.begin():
        row = await locked_execution(session, owner)
        if row.state == "settled":
            raise ScanExecutionOwnershipLost("Execution has already settled")
        stamp = await _now(session)
        row.heartbeat_at = stamp
        row.lease_expires_at = stamp + timedelta(seconds=LEASE_SECONDS)
        return row.cancel_requested_at is not None


async def mark_unresolved(
    owner: ScanExecutionOwnership, *, reason: str,
    session_factory: SessionFactory = SessionLocal,
) -> None:
    if not isinstance(reason, str) or not reason or len(reason) > 160 or "\x00" in reason:
        raise ValueError("Invalid uncertainty reason")
    async with session_factory() as session, session.begin():
        row = await locked_execution(session, owner)
        if row.state != "settled":
            row.state = "unresolved"
            row.unresolved_reason = reason


async def operation_returned(
    session: AsyncSession, owner: ScanExecutionOwnership, *, outcome: str,
) -> None:
    """Called only after the real operation and all its local cleanup were joined."""
    if not isinstance(outcome, str) or outcome not in {"completed", "failed", "cancelled"}:
        raise ValueError("Invalid execution outcome")
    row = await locked_execution(session, owner)
    if row.state == "settled" or row.phase != "executing":
        raise ScanExecutionOwnershipLost("Operation is not executing")
    row.phase = "returned"
    row.outcome = outcome
    row.operation_stopped_at = await _now(session)
    if any(x["state"] != "settled" for x in _resources(row).values()) or row.zap_owner_key:
        row.state = "unresolved"
        row.unresolved_reason = "resource-settlement-unverified"


async def supervisor_returned(
    owner: ScanExecutionOwnership, *, session_factory: SessionFactory = SessionLocal,
) -> None:
    """Record the separate join of the heartbeat/supervisor; not a lease timeout."""
    async with session_factory() as session, session.begin():
        row = await locked_execution(session, owner)
        if row.phase != "returned" or not _aware(row.operation_stopped_at):
            raise ScanExecutionUncertain("Actual operation join has not been recorded")
        row.supervisor_stopped_at = row.supervisor_stopped_at or await _now(session)


async def reconcile_returned_execution(
    scan_id: str, *, session_factory: SessionFactory = SessionLocal,
) -> bool:
    """Settle only committed join proof; no I/O, takeover, retry, or expiry waiver."""
    async with session_factory() as session, session.begin():
        # Lock order is always business scan then execution when both are needed.
        scan = await session.scalar(select(SecurityScan).where(
            SecurityScan.id == scan_id,
        ).with_for_update())
        if scan is None:
            return False
        row = await session.scalar(select(SecurityScanExecution).where(
            SecurityScanExecution.scan_id == scan_id,
        ).with_for_update())
        if row is None:
            return False
        owner = _ownership(row)
        resources = _resources(row)
        if (row.phase != "returned" or not _aware(row.operation_stopped_at)
                or not _aware(row.supervisor_stopped_at) or row.zap_owner_key is not None
                or any(x["state"] != "settled" for x in resources.values())
                or row.outcome not in {"completed", "failed", "cancelled"}):
            return False
        if row.state == "settled":
            _require_terminal_proof(row)
            return True
        if row.outcome == "completed":
            if scan.status != "completed" or scan.completed_at is None or scan.lease_token is not None:
                return False
        else:
            if scan.status != "running" or scan.lease_token != owner.ownership_nonce:
                return False
            scan.status = row.outcome
            scan.lease_token = None
            scan.completed_at = await _now(session)
            if row.outcome == "cancelled":
                scan.cancelled_at = scan.completed_at
            scan.error_code = "SECURITY_SCAN_CANCELLED" if row.outcome == "cancelled" else "SECURITY_SCAN_FAILED"
            scan.error_message = row.unresolved_reason
        scan.summary = {**dict(scan.summary or {}), "execution_cleanup": {
            "protocol_version": 1, "verified": True, "resources": len(resources),
        }}
        row.state = "settled"
        row.settled_at = await _now(session)
        row.unresolved_reason = None
        session.add(AuditEvent(
            organization_id=scan.organization_id, user_id=scan.requested_by_id,
            action="security.scan.execution_settled", resource_type="security_scan",
            resource_id=scan.id, details={"outcome": row.outcome, "resources": len(resources)},
        ))
        return True


async def request_scan_cancellation(
    session: AsyncSession, *, scan_id: str, organization_id: str, user_id: str | None,
) -> dict[str, Any]:
    """Internal tenant-scoped intent; the HTTP layer must authorize the actor.

    Caller owns commit. Acknowledgement is never proof that a running resource
    stopped. Lock ordering matches reconciliation and atomic claim registration.
    """
    with session.no_autoflush:
        scan = await session.scalar(select(SecurityScan).where(
            SecurityScan.id == scan_id, SecurityScan.organization_id == organization_id,
        ).with_for_update().execution_options(populate_existing=True))
    if scan is None:
        raise LookupError("Security scan not found")
    row = await session.scalar(select(SecurityScanExecution).where(
        SecurityScanExecution.scan_id == scan_id,
    ).with_for_update().execution_options(populate_existing=True))
    if row is not None:
        _ownership(row)
        if row.state == "settled":
            _require_terminal_proof(row)
            return {"status": "already_settled", "cleanup_verified": True}
        row.cancel_requested_at = row.cancel_requested_at or await _now(session)
        answer = {"status": "cancellation_requested", "cleanup_verified": False}
    elif _pristine_unowned(scan):
        scan.status = "cancelled"
        scan.cancelled_at = scan.completed_at = await _now(session)
        scan.summary = {**scan.summary, "cancellation_before_claim": {
            "protocol_version": 1, "verified": True,
        }}
        answer = {"status": "cancelled_before_claim", "cleanup_verified": True}
    elif _cancelled_unowned(scan):
        answer = {"status": "cancelled_before_claim", "cleanup_verified": True}
    else:
        answer = {"status": "reconciliation_required", "cleanup_verified": False}
    session.add(AuditEvent(
        organization_id=organization_id, user_id=user_id,
        action="security.scan.cancellation_requested", resource_type="security_scan",
        resource_id=scan_id, details=answer,
    ))
    await session.flush()
    return answer


def _pristine_unowned(scan: SecurityScan) -> bool:
    return (
        scan.status == "queued" and scan.attempts == 0 and scan.max_attempts > 0
        and scan.started_at is None and scan.lease_token is None
        and scan.completed_at is None and scan.cancelled_at is None
        and scan.error_code is None and scan.error_message is None
        and isinstance(scan.summary, dict) and "_execution_guard" not in scan.summary
        and "cancellation_before_claim" not in scan.summary and "execution_cleanup" not in scan.summary
    )


def _cancelled_unowned(scan: SecurityScan) -> bool:
    marker = scan.summary.get("cancellation_before_claim") if isinstance(scan.summary, dict) else None
    return (
        scan.status == "cancelled" and scan.attempts == 0 and scan.started_at is None
        and scan.lease_token is None and _aware(scan.cancelled_at)
        and scan.cancelled_at == scan.completed_at and isinstance(marker, dict)
        and set(marker) == {"protocol_version", "verified"}
        and type(marker["protocol_version"]) is int and marker["protocol_version"] == 1
        and marker["verified"] is True and "_execution_guard" not in scan.summary
        and scan.error_code is None and scan.error_message is None
    )


def _require_terminal_proof(row: SecurityScanExecution) -> None:
    if (row.phase != "returned" or not _aware(row.operation_stopped_at)
            or not _aware(row.supervisor_stopped_at) or not _aware(row.settled_at)
            or row.zap_owner_key is not None or row.outcome not in {"completed", "failed", "cancelled"}
            or any(x["state"] != "settled" for x in _resources(row).values())):
        raise ScanExecutionUncertain("Terminal execution has inconsistent settlement proof")


async def execution_snapshot(
    *, session_factory: SessionFactory = SessionLocal,
) -> dict[str, Any]:
    """Consistent known blockers only; no deployment or private nonce output."""
    async with session_factory() as session, session.begin():
        if session.get_bind().dialect.name != "postgresql":
            raise ScanExecutionUncertain("Execution snapshot requires PostgreSQL")
        # Both inventories must describe one snapshot: a new claim between two
        # READ COMMITTED queries must not disappear from both lists.
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
        authority = await read_admission_snapshot(session, required_scope="security_scan_requests")
        stamp = await _now(session)
        rows = (await session.scalars(select(SecurityScanExecution).order_by(SecurityScanExecution.id))).all()
        observed = []
        registered = set()
        for row in rows:
            _ownership(row)
            registered.add(row.scan_id)
            resources = _resources(row)
            if row.state == "settled":
                _require_terminal_proof(row)
                continue
            observed.append({
                "execution_id": row.id, "scan_id": row.scan_id, "state": row.state,
                "phase": row.phase, "expired": row.lease_expires_at <= stamp,
                "unfinished_resources": sum(x["state"] != "settled" for x in resources.values()),
                "cancel_requested": row.cancel_requested_at is not None,
            })
        scans = (await session.scalars(select(SecurityScan).order_by(SecurityScan.id))).all()
        legacy = [scan.id for scan in scans if scan.id not in registered
                  and not _pristine_unowned(scan) and not _cancelled_unowned(scan)]
        return {
            "scope": CONSUMER, "observed_at": stamp.isoformat(), "executions": observed,
            "legacy_unverified_scan_ids": legacy, "blocker_count": len(observed) + len(legacy),
            "is_clear": not observed and not legacy,
            "admission_closed": not authority.is_open,
            "coverage_unverified": True, "full_host_closure": False,
        }
