"""Durable delivery worker for Phase 29E communication channels."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import time
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.db.base import SessionLocal
from app.services.communications import claim_due_deliveries, process_delivery
from sqlalchemy import text

logger = get_logger(__name__)


class CommunicationWorker:
    def __init__(self) -> None:
        self.stop_event = asyncio.Event()
        self.health_path = Path(settings.COMMUNICATION_WORKER_HEALTH_FILE)
        self.processed = 0
        self.errors = 0
        self.last_delivery_id: str | None = None

    async def preflight(self) -> None:
        async with SessionLocal() as session:
            ready = bool(
                await session.scalar(
                    text(
                        "SELECT "
                        "to_regclass('notifications') IS NOT NULL "
                        "AND to_regclass('notification_deliveries') IS NOT NULL "
                        "AND to_regclass('notification_delivery_attempts') IS NOT NULL "
                        "AND to_regclass('communication_endpoints') IS NOT NULL"
                    )
                )
            )
        if not ready:
            raise RuntimeError("Communication worker database schema is not current")

    async def run_once(self) -> int:
        async with SessionLocal() as session:
            delivery_ids = await claim_due_deliveries(session, limit=25)
        for delivery_id in delivery_ids:
            try:
                async with SessionLocal() as session:
                    await process_delivery(session, delivery_id)
                self.processed += 1
                self.last_delivery_id = delivery_id
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.errors += 1
                logger.error(
                    "Communication delivery cycle failed",
                    delivery_id=delivery_id,
                    error_type=type(exc).__name__,
                )
        self.write_health("running")
        return len(delivery_ids)

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
                    pass
        self.write_health("stopped")

    def write_health(self, status: str) -> None:
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
            pass
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
