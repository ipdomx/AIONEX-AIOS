"""CLI bridge for root-owned host runtime watcher -> durable Owner notification.

Only sanitized event metadata enters the application. Docker access remains outside
all application containers.
"""
from __future__ import annotations

import argparse
import asyncio
import re

from app.db.base import SessionLocal
from app.services import communications
from app.services.lifecycle_alerts import owner_alert_channels

_SAFE = re.compile(r"^[A-Za-z0-9_.:-]{1,120}$")
_EVENTS = {"restart", "unhealthy", "missing", "recovered"}


def _safe(value: str, *, label: str) -> str:
    normalized = value.strip()
    if not _SAFE.fullmatch(normalized):
        raise ValueError(f"invalid {label}")
    return normalized


async def emit(*, event: str, service: str, transition: int, restart_count: int) -> int:
    event = _safe(event, label="event")
    service = _safe(service, label="service")
    if event not in _EVENTS:
        raise ValueError("unsupported event")
    if not 0 <= transition <= 1_000_000_000 or not 0 <= restart_count <= 1_000_000_000:
        raise ValueError("invalid runtime counter")

    if event == "restart":
        title = "Production container restarted"
        message = (
            f"Production service {service} restart count increased to {restart_count}. "
            "Review runtime health and logs if this was not a controlled deployment."
        )
        severity = "warning"
    elif event in {"unhealthy", "missing"}:
        title = "Production container needs attention"
        message = (
            f"Production service {service} is {event}. The host watcher confirmed the "
            "condition on consecutive checks."
        )
        severity = "critical"
    else:
        title = "Production container recovered"
        message = f"Production service {service} returned to a healthy running state."
        severity = "info"

    async with SessionLocal() as session:
        notifications = await communications.notify_audience(
            session,
            organization_id="platform",
            audience="platform_owner",
            event_key=f"operations.host.{event}",
            category="operations",
            title=title,
            message=message,
            severity=severity,
            channels=owner_alert_channels(),
            source_type="container_runtime",
            source_id=service,
            correlation_id=service,
            dedupe_prefix=f"host-runtime:{service}:{event}:{transition}:{restart_count}",
            payload={
                "service": service,
                "event": event,
                "transition": transition,
                "restart_count": restart_count,
            },
            respect_preferences=False,
        )
        await session.commit()
    await communications.publish_many(notifications)
    return len(notifications)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", required=True, choices=sorted(_EVENTS))
    parser.add_argument("--service", required=True)
    parser.add_argument("--transition", required=True, type=int)
    parser.add_argument("--restart-count", default=0, type=int)
    args = parser.parse_args()
    asyncio.run(
        emit(
            event=args.event,
            service=args.service,
            transition=args.transition,
            restart_count=args.restart_count,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
