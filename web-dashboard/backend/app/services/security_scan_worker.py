"""Security Lab worker with conservative, one-shot execution admission.

A cancelled await, an exception, an expired lease and a terminal-looking business
row are not evidence that child processes, threads or remote work have stopped.
This guard prevents automatic replay; it is NOT a full execution/drain registry.
Uncertain attempts remain running with an explicit reconciliation-required error.
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
from app.db.models import AuditEvent, OwnerControlRecord, SecurityScan, uuid_str
from app.services import security_tools
from app.services.host_maintenance_admission import HostMaintenanceClosed
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
    def __init__(self) -> None:
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
        async with SessionLocal() as session:
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
        """Claim untouched backlog only, under the existing maintenance switch.

        No age-based recovery or automatic retry is safe until external resource
        settlement is established. Schema 6 remains partial request coverage;
        using its switch here does not upgrade that coverage claim.
        """
        async with SessionLocal() as session:
            await require_scan_admission(session)
            summary = cast(SecurityScan.summary, JSONB)
            scan = await session.scalar(
                select(SecurityScan)
                .where(
                    SecurityScan.status == "queued",
                    SecurityScan.attempts == 0,
                    SecurityScan.max_attempts > 0,
                    SecurityScan.started_at.is_(None),
                    SecurityScan.completed_at.is_(None),
                    SecurityScan.cancelled_at.is_(None),
                    SecurityScan.lease_token.is_(None),
                    SecurityScan.error_code.is_(None),
                    SecurityScan.error_message.is_(None),
                    func.jsonb_typeof(summary) == "object",
                    ~func.jsonb_exists(summary, GUARD_KEY),
                )
                .order_by(SecurityScan.created_at, SecurityScan.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if scan is None:
                return None
            token = str(uuid4())
            scan.status = "running"
            scan.started_at = now()
            scan.lease_token = token
            scan.attempts += 1
            _set_execution_phase(scan, "claimed")
            session.add(
                AuditEvent(
                    organization_id=scan.organization_id,
                    user_id=scan.requested_by_id,
                    action="security.scan.claimed",
                    resource_type="security_scan",
                    resource_id=scan.id,
                    details={"attempt": scan.attempts, "reclaimed": False},
                )
            )
            await session.commit()
            return scan.id, token

    async def _begin_execution(self, scan_id: str, token: str) -> bool:
        """Commit the one-shot start before any scanner I/O, including policy I/O."""
        async with SessionLocal() as session:
            await require_scan_admission(session)
            scan = await session.scalar(
                select(SecurityScan)
                .where(
                    SecurityScan.id == scan_id,
                    SecurityScan.status == "running",
                    SecurityScan.lease_token == token,
                )
                .with_for_update(skip_locked=True)
            )
            if scan is None or _execution_phase(scan) != "claimed":
                return False
            _set_execution_phase(scan, "executing")
            await session.commit()
            return True

    async def _mark_unresolved(self, scan_id: str, token: str, error_type: str) -> None:
        """Preserve the exact uncertain owner; do not clear, requeue or finish it."""
        async with SessionLocal() as session:
            scan = await session.scalar(
                select(SecurityScan)
                .where(
                    SecurityScan.id == scan_id,
                    SecurityScan.status == "running",
                    SecurityScan.lease_token == token,
                )
                .with_for_update()
            )
            if scan is None or _execution_phase(scan) != "executing":
                return
            _set_execution_phase(scan, "unresolved")
            scan.error_code = "SECURITY_SCAN_RECONCILIATION_REQUIRED"
            scan.error_message = error_type
            scan.completed_at = None
            session.add(
                AuditEvent(
                    organization_id=scan.organization_id,
                    user_id=scan.requested_by_id,
                    action="security.scan.reconciliation_required",
                    resource_type="security_scan",
                    resource_id=scan.id,
                    details={"error_type": error_type, "cleanup_verified": False},
                )
            )
            await session.commit()

    async def run_claim(self, scan_id: str, token: str) -> None:
        if not await self._begin_execution(scan_id, token):
            return
        try:
            async with SessionLocal() as session:
                scan = await session.scalar(
                    select(SecurityScan)
                    .where(
                        SecurityScan.id == scan_id,
                        SecurityScan.status == "running",
                        SecurityScan.lease_token == token,
                    )
                    .with_for_update()
                )
                if scan is None or _execution_phase(scan) != "executing":
                    return
                policy = await get_policy(session)
                timeout_seconds = max(
                    60, min(int(policy.get("max_scan_runtime_seconds", 1800)), 7200)
                )
                await asyncio.wait_for(
                    execute_scan(session, scan), timeout=timeout_seconds
                )
                _set_execution_phase(scan, "returned")
                await session.commit()
        except BaseException as exc:
            # asyncio.CancelledError is deliberately included. A second cancel
            # must not interrupt recording the uncertain attempt. If recording
            # itself fails, the committed executing marker still prevents replay.
            reconciliation = asyncio.create_task(
                self._mark_unresolved(scan_id, token, type(exc).__name__)
            )
            try:
                while not reconciliation.done():
                    try:
                        await asyncio.shield(reconciliation)
                    except asyncio.CancelledError:
                        continue
                reconciliation.result()
            except Exception:
                logger.exception("Security scan reconciliation recording failed")
            raise

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
