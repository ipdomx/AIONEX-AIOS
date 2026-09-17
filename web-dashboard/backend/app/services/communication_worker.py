"""Owned external notification dispatch with durable maintenance admission."""

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
from app.services.communications import (
    NotificationDispatcher,
    NotificationSessionFactory,
    claim_due_deliveries,
    process_delivery,
)
from app.services.host_maintenance_admission import (
    HostMaintenanceClosed,
    read_admission_snapshot,
)
from app.services.host_maintenance_notifications import CONSUMER
from sqlalchemy import text

logger = get_logger(__name__)

_CYCLE_COLUMNS = {
    "id", "resource_id", "consumer", "worker_incarnation", "admitted_generation",
    "ownership_nonce", "state", "phase", "job_id", "started_at", "heartbeat_at",
    "lease_expires_at", "unresolved_reason",
}


class CommunicationWorker:
    def __init__(
        self,
        *,
        session_factory: NotificationSessionFactory | None = None,
        dispatcher: NotificationDispatcher | None = None,
        heartbeat_interval_seconds: float = 20.0,
    ) -> None:
        if heartbeat_interval_seconds <= 0:
            raise ValueError("Notification heartbeat interval must be positive")
        self.session_factory = session_factory if session_factory is not None else SessionLocal
        self.dispatcher = dispatcher
        self.heartbeat_interval_seconds = heartbeat_interval_seconds
        self.worker_incarnation = str(uuid4())
        self.stop_event = asyncio.Event()
        self.health_path = Path(settings.COMMUNICATION_WORKER_HEALTH_FILE)
        self.processed = 0
        self.errors = 0
        self.last_delivery_id: str | None = None

    async def preflight(self) -> None:
        """Readiness validates coverage and schema without opening admission."""
        async with self.session_factory() as session:
            ready = bool(
                await session.scalar(
                    text(
                        "SELECT "
                        "to_regclass('notifications') IS NOT NULL "
                        "AND to_regclass('notification_deliveries') IS NOT NULL "
                        "AND to_regclass('notification_delivery_attempts') IS NOT NULL "
                        "AND to_regclass('communication_endpoints') IS NOT NULL "
                        "AND to_regclass('host_maintenance_work_cycles') IS NOT NULL"
                    )
                )
            )
            if not ready:
                raise RuntimeError("Communication worker database schema is not current")
            cycle_columns = set(
                (
                    await session.scalars(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_schema = current_schema() "
                            "AND table_name = 'host_maintenance_work_cycles'"
                        )
                    )
                ).all()
            )
            attempt_columns = set(
                (
                    await session.scalars(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_schema = current_schema() "
                            "AND table_name = 'notification_delivery_attempts'"
                        )
                    )
                ).all()
            )
            if not _CYCLE_COLUMNS <= cycle_columns or not {
                "dispatch_protocol_version", "dispatch_outcome"
            } <= attempt_columns:
                raise RuntimeError("Communication worker ownership schema is not current")
            # A valid CLOSED dispatch scope is healthy and waits for reopening.
            await read_admission_snapshot(session, required_scope=CONSUMER)

    async def run_once(self) -> int:
        if self.stop_event.is_set():
            return 0
        try:
            async with self.session_factory() as session:
                ownerships = await claim_due_deliveries(
                    session, worker_incarnation=self.worker_incarnation, limit=1
                )
        except HostMaintenanceClosed:
            self.write_health("running")
            return 0
        if not ownerships:
            self.write_health("running")
            return 0
        ownership = ownerships[0]
        try:
            await process_delivery(
                ownership,
                session_factory=self.session_factory,
                dispatcher=self.dispatcher,
                heartbeat_interval_seconds=self.heartbeat_interval_seconds,
                health_callback=lambda: self.write_health("running"),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.errors += 1
            logger.error(
                "Communication delivery cycle failed",
                delivery_id=ownership.delivery_id,
                error_type=type(exc).__name__,
            )
            self.write_health("degraded")
            return 1
        self.processed += 1
        self.last_delivery_id = ownership.delivery_id
        self.write_health("running")
        return 1

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
                logger.error(
                    "Communication worker cycle failed",
                    error_type=type(exc).__name__,
                )
                processed = 0
                self.write_health("degraded")
            if processed == 0:
                try:
                    await asyncio.wait_for(
                        self.stop_event.wait(),
                        timeout=settings.COMMUNICATION_WORKER_POLL_SECONDS,
                    )
                except TimeoutError:
                    continue
        self.write_health("stopped")

    def write_health(self, status: str) -> None:
        """Publish explicitly excluded control-plane liveness metadata."""
        payload = {
            "status": status,
            "checked_at": datetime.now(UTC).isoformat(),
            "checked_at_epoch": time.time(),
            "processed": self.processed,
            "errors": self.errors,
            "last_delivery_id": self.last_delivery_id,
            "secret_returned": False,
        }
        self.health_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.health_path.with_name(f".{self.health_path.name}.tmp")
        temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.replace(temporary, self.health_path)


def healthcheck(path: str | Path, *, maximum_age_seconds: float = 120.0) -> int:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        age = time.time() - float(payload["checked_at_epoch"])
        healthy = payload.get("status") == "running" and 0 <= age <= maximum_age_seconds
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        healthy = False
    return 0 if healthy else 1


async def async_main() -> int:
    worker = CommunicationWorker()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, worker.stop_event.set)
        except NotImplementedError:
            logger.debug("Notification signal handler is unavailable")
    await worker.run_forever()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--healthcheck", action="store_true")
    args = parser.parse_args()
    if args.healthcheck:
        return healthcheck(settings.COMMUNICATION_WORKER_HEALTH_FILE)
    setup_logging()
    try:
        return asyncio.run(async_main())
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        logger.error(
            "Communication worker startup failed", error_type=type(exc).__name__
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
