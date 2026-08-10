"""Durable Security Lab worker."""

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

from sqlalchemy import and_, or_, select

from app.core.logging import get_logger, setup_logging
from app.db.base import SessionLocal
from app.db.models import AuditEvent, OwnerControlRecord, SecurityScan, uuid_str
from app.services.security_scanning import execute_scan
from app.services import security_tools
from app.services.security_fabric import get_policy

logger = get_logger(__name__)


def now() -> datetime:
    return datetime.now(UTC)


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
        self.lease_seconds = max(
            60, int(os.getenv("SECURITY_SCAN_JOB_LEASE_SECONDS", "1800"))
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
        stale = now() - timedelta(seconds=self.lease_seconds)
        async with SessionLocal() as session:
            scan = await session.scalar(
                select(SecurityScan)
                .where(
                    or_(
                        SecurityScan.status == "queued",
                        and_(
                            SecurityScan.status == "running",
                            SecurityScan.updated_at < stale,
                        ),
                    ),
                    SecurityScan.attempts < SecurityScan.max_attempts,
                )
                .order_by(SecurityScan.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if scan is None:
                return None
            token = str(uuid4())
            reclaimed = scan.status == "running"
            scan.status = "running"
            scan.started_at = scan.started_at or now()
            scan.lease_token = token
            scan.attempts += 1
            scan.error_code = None
            scan.error_message = None
            session.add(
                AuditEvent(
                    organization_id=scan.organization_id,
                    user_id=scan.requested_by_id,
                    action="security.scan.claimed",
                    resource_type="security_scan",
                    resource_id=scan.id,
                    details={"attempt": scan.attempts, "reclaimed": reclaimed},
                )
            )
            await session.commit()
            return scan.id, token

    async def run_claim(self, scan_id: str, token: str) -> None:
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
            if scan is None:
                return
            try:
                policy = await get_policy(session)
                timeout_seconds = max(
                    60, min(int(policy.get("max_scan_runtime_seconds", 1800)), 7200)
                )
                await asyncio.wait_for(
                    execute_scan(session, scan), timeout=timeout_seconds
                )
                await session.commit()
            except Exception as exc:
                await session.rollback()
                async with SessionLocal() as failure_session:
                    failed = await failure_session.scalar(
                        select(SecurityScan)
                        .where(
                            SecurityScan.id == scan_id,
                            SecurityScan.lease_token == token,
                        )
                        .with_for_update()
                    )
                    if failed is not None:
                        terminal = failed.attempts >= failed.max_attempts
                        failed.status = "failed" if terminal else "queued"
                        failed.error_code = "SECURITY_SCAN_FAILED"
                        failed.error_message = type(exc).__name__
                        failed.completed_at = now() if terminal else None
                        failed.lease_token = None
                        failure_session.add(
                            AuditEvent(
                                organization_id=failed.organization_id,
                                user_id=failed.requested_by_id,
                                action="security.scan.failed",
                                resource_type="security_scan",
                                resource_id=failed.id,
                                details={
                                    "error_type": type(exc).__name__,
                                    "terminal": terminal,
                                },
                            )
                        )
                        await failure_session.commit()
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
