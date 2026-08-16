"""Periodic Phase 29G production observability worker."""

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
from app.db.redis import close_redis, init_redis
from app.services import communications
from app.services.growth_controlled_pilots import reconcile_runtime_pilots
from app.services.growth_paid_live_execution import reconcile_stale_live_executions
from app.services.lifecycle_alerts import run_account_lifecycle_alerts
from app.services.operations_assurance import record_observation_cycle

logger = get_logger(__name__)


class OperationsObserver:
    def __init__(self) -> None:
        self.stop_event = asyncio.Event()
        self.health_path = Path(settings.OPERATIONS_OBSERVER_HEALTH_FILE)
        self.cycles = 0
        self.errors = 0
        self.last_lifecycle_alert_monotonic = 0.0

    async def preflight(self) -> None:
        async with SessionLocal() as session:
            await record_observation_cycle(session)
            await session.rollback()

    def write_health(self, status: str) -> None:
        payload = {
            "status": status,
            "checked_at": datetime.now(UTC).isoformat(),
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

    async def run_once(self) -> None:
        current_monotonic = time.monotonic()
        run_lifecycle_alerts = (
            self.last_lifecycle_alert_monotonic <= 0
            or current_monotonic - self.last_lifecycle_alert_monotonic
            >= settings.ACCOUNT_LIFECYCLE_ALERT_INTERVAL_SECONDS
        )
        # Commit GS-12 safety reconciliation independently before unrelated
        # observability/lifecycle work. A later alerting failure must never roll
        # back an auto-disarm that protects provider mutation/spend.
        async with SessionLocal() as session:
            pilot_runtime = await reconcile_runtime_pilots(session)
            live_execution_runtime = await reconcile_stale_live_executions(session)
            await session.commit()

        async with SessionLocal() as session:
            await record_observation_cycle(session)
            notifications = (
                await run_account_lifecycle_alerts(session)
                if run_lifecycle_alerts
                else []
            )
            await session.commit()
        if run_lifecycle_alerts:
            self.last_lifecycle_alert_monotonic = current_monotonic
        if pilot_runtime["auto_disarmed"]:
            logger.warning(
                "GS-12 runtime guard auto-disarmed controlled pilots",
                auto_disarmed=pilot_runtime["auto_disarmed"],
            )
        if live_execution_runtime["executions_marked_manual_review"]:
            logger.warning(
                "GS-12 live execution reconciliation requires manual review",
                executions=live_execution_runtime["executions_marked_manual_review"],
                pilots_auto_disarmed=live_execution_runtime["pilots_auto_disarmed"],
            )
        await communications.publish_many(notifications)
        self.cycles += 1
        self.write_health("running")

    async def run_forever(self) -> None:
        await self.preflight()
        self.write_health("running")
        while not self.stop_event.is_set():
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.errors += 1
                logger.error(
                    "Operations observer cycle failed",
                    error_type=type(exc).__name__,
                )
                self.write_health("degraded")
            try:
                await asyncio.wait_for(
                    self.stop_event.wait(),
                    timeout=settings.OPERATIONS_OBSERVER_INTERVAL_SECONDS,
                )
            except TimeoutError:
                pass
        self.write_health("stopped")


def healthcheck(path: str | Path, maximum_age_seconds: float | None = None) -> int:
    maximum_age = maximum_age_seconds or max(
        90.0, float(settings.OPERATIONS_OBSERVER_INTERVAL_SECONDS) * 3.0
    )
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        age = time.time() - float(payload["checked_at_epoch"])
        healthy = payload.get("status") == "running" and 0 <= age <= maximum_age
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        healthy = False
    return 0 if healthy else 1


async def async_main() -> int:
    observer = OperationsObserver()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, observer.stop_event.set)
        except NotImplementedError:
            pass
    await init_redis()
    try:
        await observer.run_forever()
        return 0
    finally:
        await close_redis()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--healthcheck", action="store_true")
    args = parser.parse_args()
    if args.healthcheck:
        return healthcheck(settings.OPERATIONS_OBSERVER_HEALTH_FILE)
    setup_logging()
    try:
        return asyncio.run(async_main())
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        logger.error(
            "Operations observer startup failed",
            error_type=type(exc).__name__,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
