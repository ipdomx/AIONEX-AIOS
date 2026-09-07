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
_EVENTS = {
    "restart", "unhealthy", "missing", "recovered",
    "capacity_warning", "capacity_critical", "capacity_recovered",
}
_CAPACITY_METRICS = {
    "cpu_pct", "memory_pct", "disk_pct", "load_pct", "network_pct", "swap_pct"
}


def _safe(value: str, *, label: str) -> str:
    normalized = value.strip()
    if not _SAFE.fullmatch(normalized):
        raise ValueError(f"invalid {label}")
    return normalized


async def emit(
    *,
    event: str,
    service: str,
    transition: int,
    restart_count: int,
    metric: str | None = None,
    value: float | None = None,
    threshold: float | None = None,
) -> int:
    event = _safe(event, label="event")
    service = _safe(service, label="service")
    if event not in _EVENTS:
        raise ValueError("unsupported event")
    if not 0 <= transition <= 1_000_000_000 or not 0 <= restart_count <= 1_000_000_000:
        raise ValueError("invalid runtime counter")

    capacity_event = event.startswith("capacity_")
    safe_metric: str | None = None
    safe_value: float | None = None
    safe_threshold: float | None = None
    if capacity_event:
        safe_metric = _safe(metric or "", label="metric")
        if safe_metric not in _CAPACITY_METRICS:
            raise ValueError("unsupported capacity metric")
        if value is None or threshold is None:
            raise ValueError("capacity metric value and threshold are required")
        safe_value = float(value)
        safe_threshold = float(threshold)
        if not 0.0 <= safe_value <= 100.0 or not 0.0 <= safe_threshold <= 100.0:
            raise ValueError("invalid capacity percentage")

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
    elif event == "recovered":
        title = "Production container recovered"
        message = f"Production service {service} returned to a healthy running state."
        severity = "info"
    elif event == "capacity_warning":
        title = "Server upgrade recommended / يوصى بترقية السيرفر"
        message = (
            f"Production host capacity is approaching the measured safe launch boundary: "
            f"{safe_metric} is {safe_value:.1f}% (warning threshold {safe_threshold:.1f}%). "
            "Review capacity and prepare a server upgrade before sustained demand grows further."
        )
        severity = "warning"
    elif event == "capacity_critical":
        title = "Server upgrade required / ترقية السيرفر مطلوبة"
        message = (
            f"Production host capacity crossed a critical sustained boundary: {safe_metric} is "
            f"{safe_value:.1f}% (critical threshold {safe_threshold:.1f}%). "
            "Upgrade server capacity or reduce load immediately; AIONEX will send a recovery notice "
            "after the metric remains back in the safe range."
        )
        severity = "critical"
    else:
        title = "Server capacity recovered / سعة السيرفر عادت للطبيعي"
        message = (
            f"Production host capacity metric {safe_metric} returned to the safe range at "
            f"{safe_value:.1f}%. The previous server-capacity warning is no longer active."
        )
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
            source_type="host_capacity" if capacity_event else "container_runtime",
            source_id=safe_metric if capacity_event else service,
            correlation_id=(f"host-capacity:{safe_metric}" if capacity_event else service),
            dedupe_prefix=(
                f"host-capacity:{safe_metric}:{event}:{transition}"
                if capacity_event
                else f"host-runtime:{service}:{event}:{transition}:{restart_count}"
            ),
            payload=(
                {
                    "metric": safe_metric,
                    "value_pct": safe_value,
                    "threshold_pct": safe_threshold,
                    "event": event,
                    "transition": transition,
                    "upgrade_recommended": event in {"capacity_warning", "capacity_critical"},
                }
                if capacity_event
                else {
                    "service": service,
                    "event": event,
                    "transition": transition,
                    "restart_count": restart_count,
                }
            ),
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
    parser.add_argument("--metric")
    parser.add_argument("--value", type=float)
    parser.add_argument("--threshold", type=float)
    args = parser.parse_args()
    asyncio.run(
        emit(
            event=args.event,
            service=args.service,
            transition=args.transition,
            restart_count=args.restart_count,
            metric=args.metric,
            value=args.value,
            threshold=args.threshold,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
