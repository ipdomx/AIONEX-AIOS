"""Fail-safe Owner alerts for production runtime health and critical incidents.

The application deliberately has no Docker socket.  Service health is derived from
existing network/database probes.  Host-level restart counters are handled by the
separate root-owned systemd watcher and delivered through ``runtime_host_alert``.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Alert, OwnerControlRecord
from app.services import communications, operations_assurance
from app.services.lifecycle_alerts import owner_alert_channels

RUNTIME_HEALTH_DOMAIN = "operations-runtime-health"


async def _health_records(session: AsyncSession) -> dict[str, OwnerControlRecord]:
    rows = list(
        (
            await session.scalars(
                select(OwnerControlRecord).where(
                    OwnerControlRecord.domain == RUNTIME_HEALTH_DOMAIN
                )
            )
        ).all()
    )
    return {row.resource_id: row for row in rows}


async def run_runtime_owner_alerts(session: AsyncSession) -> list:
    """Persist health transitions and return newly-created Owner notifications.

    The first observation establishes a baseline without paging the Owner. Later
    healthy->unhealthy and unhealthy->healthy transitions are notified exactly once
    per persisted transition version. Critical Alert rows are deduped by alert ID.
    """

    notifications: list = []
    inventory = await operations_assurance.service_inventory(session)
    records = await _health_records(session)

    for component in inventory:
        component_id = str(component["id"])
        current = str(component.get("health") or "unhealthy").strip().lower()
        current = "healthy" if current == "healthy" else "unhealthy"
        record = records.get(component_id)
        if record is None:
            record = OwnerControlRecord(
                domain=RUNTIME_HEALTH_DOMAIN,
                resource_id=component_id,
                status="active",
                enabled=True,
                payload={
                    "health": current,
                    "transition": 0,
                    "name": str(component.get("name") or component_id)[:200],
                },
            )
            session.add(record)
            records[component_id] = record
            continue

        payload = dict(record.payload or {})
        previous = str(payload.get("health") or "unknown")
        if previous == current:
            continue

        transition = max(0, int(payload.get("transition", 0) or 0)) + 1
        name = str(component.get("name") or component_id)[:200]
        record.payload = {
            **payload,
            "health": current,
            "transition": transition,
            "name": name,
        }
        record.version += 1
        record.status = "active"
        record.enabled = True

        if current == "unhealthy":
            event_key = "operations.runtime.service_unhealthy"
            title = "Production service needs attention"
            message = (
                f"Production component {name} became unavailable. AIONEX will keep "
                "probing it and will send a recovery notice when it returns."
            )
            severity = "critical"
        else:
            event_key = "operations.runtime.service_recovered"
            title = "Production service recovered"
            message = f"Production component {name} is healthy again."
            severity = "info"

        notifications.extend(
            await communications.notify_audience(
                session,
                organization_id="platform",
                audience="platform_owner",
                event_key=event_key,
                category="operations",
                title=title,
                message=message,
                severity=severity,
                channels=owner_alert_channels(),
                source_type="runtime_component",
                source_id=component_id,
                correlation_id=component_id,
                dedupe_prefix=(
                    f"runtime-health:{component_id}:transition:{transition}:{current}"
                ),
                payload={
                    "component_id": component_id,
                    "health": current,
                    "transition": transition,
                },
                respect_preferences=False,
            )
        )

    critical_alerts = list(
        (
            await session.scalars(
                select(Alert).where(
                    Alert.severity == "critical",
                    Alert.status != "resolved",
                )
                .order_by(Alert.created_at.desc())
                .limit(100)
            )
        ).all()
    )
    for alert in critical_alerts:
        notifications.extend(
            await communications.notify_audience(
                session,
                organization_id="platform",
                audience="platform_owner",
                event_key="operations.runtime.critical_alert",
                category="operations",
                title="Critical platform alert requires review",
                message=(
                    f"A critical platform alert from {str(alert.source)[:120]} is active. "
                    "Review the Owner monitoring console for details."
                ),
                severity="critical",
                channels=owner_alert_channels(),
                source_type="alert",
                source_id=alert.id,
                correlation_id=alert.id,
                dedupe_prefix=f"runtime-critical-alert:{alert.id}",
                payload={"alert_id": alert.id, "source": str(alert.source)[:120]},
                respect_preferences=False,
            )
        )
    return notifications
