"""Authenticated monitoring and observability endpoints backed by SQL."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Optional

from app.core.auth import (
    UserRecord,
    require_permissions,
    require_super_owner,
)
from app.db.base import get_db
from app.db.models import (
    Alert,
    AuditEvent,
    BackupRecord,
    DisasterRecoveryRun,
    MetricSample,
    uuid_str,
)
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _serialize_metric(sample: MetricSample) -> dict[str, Any]:
    return {
        "id": sample.id,
        "name": sample.name,
        "resource": sample.resource,
        "timestamp": _iso(sample.timestamp),
        "value": sample.value,
        "labels": sample.labels or {},
    }


def _serialize_alert(alert: Alert) -> dict[str, Any]:
    return {
        "id": alert.id,
        "organization_id": alert.organization_id,
        "title": alert.title,
        "description": alert.description,
        "severity": alert.severity,
        "status": alert.status,
        "source": alert.source,
        "created_at": _iso(alert.created_at),
        "updated_at": _iso(alert.updated_at),
        "acknowledged_at": _iso(alert.acknowledged_at),
        "resolved_at": _iso(alert.resolved_at),
    }


def _alert_scope(actor: UserRecord):
    if actor.role == "Super Owner":
        return True
    return or_(
        Alert.organization_id == actor.organization_id,
        Alert.organization_id.is_(None),
    )


def _metric_visible(sample: MetricSample, actor: UserRecord) -> bool:
    if actor.role == "Super Owner":
        return True
    return (sample.labels or {}).get("organization_id") == actor.organization_id


def _serialize_log(event: AuditEvent) -> dict[str, Any]:
    details = event.details or {}
    return {
        "id": event.id,
        "timestamp": _iso(event.created_at),
        "level": details.get("level", "info"),
        "service": details.get("service", "runtime"),
        "message": details.get("message", event.action),
        "trace_id": details.get("trace_id"),
    }


@router.get("/metrics")
async def get_metrics(
    metric_type: Optional[str] = None,
    resource: Optional[str] = None,
    hours: int = Query(24, ge=1, le=168),
    actor: UserRecord = Depends(require_permissions("monitoring:read")),
    session: AsyncSession = Depends(get_db),
):
    statement = select(MetricSample).where(
        MetricSample.timestamp >= datetime.now(UTC) - timedelta(hours=hours)
    )
    if metric_type:
        statement = statement.where(MetricSample.name == metric_type)
    if resource:
        statement = statement.where(MetricSample.resource == resource)
    samples = (
        await session.scalars(statement.order_by(MetricSample.timestamp.asc()))
    ).all()
    visible = [sample for sample in samples if _metric_visible(sample, actor)]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for sample in visible:
        grouped.setdefault(sample.name, []).append(_serialize_metric(sample))
    if metric_type:
        return {metric_type: grouped.get(metric_type, [])}
    return grouped


@router.post("/metrics/{metric_name}")
async def record_metric(
    metric_name: str,
    value: float,
    resource: str = "platform",
    status: (
        Literal[
            "healthy",
            "ready",
            "ok",
            "operational",
            "warning",
            "critical",
            "failed",
        ]
        | None
    ) = None,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    labels: dict[str, str] = {"organization_id": actor.organization_id}
    if status is not None:
        labels["status"] = status
    sample = MetricSample(
        name=metric_name.strip(),
        resource=resource.strip(),
        value=float(value),
        labels=labels,
    )
    session.add(sample)
    await session.commit()
    return _serialize_metric(sample)


@router.get("/logs")
async def get_logs(
    level: Optional[str] = None,
    service: Optional[str] = None,
    search: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    actor: UserRecord = Depends(require_permissions("monitoring:read")),
    session: AsyncSession = Depends(get_db),
):
    statement = select(AuditEvent).where(
        AuditEvent.action == "monitoring.log",
        or_(
            AuditEvent.organization_id == actor.organization_id,
            AuditEvent.organization_id.is_(None),
        ),
    )
    rows = (
        await session.scalars(statement.order_by(AuditEvent.created_at.desc()))
    ).all()
    items = [_serialize_log(row) for row in rows]
    if level:
        items = [item for item in items if item["level"] == level]
    if service:
        items = [item for item in items if item["service"] == service]
    if search:
        needle = search.lower()
        items = [item for item in items if needle in item["message"].lower()]
    return items[skip : skip + limit]


@router.post("/logs")
async def create_log(
    level: str,
    service: str,
    message: str,
    trace_id: str | None = None,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    event = AuditEvent(
        organization_id=actor.organization_id,
        user_id=actor.id,
        action="monitoring.log",
        resource_type="monitoring_log",
        resource_id=service.strip(),
        details={
            "level": level.strip(),
            "service": service.strip(),
            "message": message.strip(),
            "trace_id": trace_id or uuid_str(),
        },
    )
    session.add(event)
    await session.commit()
    return _serialize_log(event)


@router.get("/alerts")
async def get_alerts(
    severity: Optional[str] = None,
    status: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    actor: UserRecord = Depends(require_permissions("monitoring:read")),
    session: AsyncSession = Depends(get_db),
):
    statement = select(Alert).where(_alert_scope(actor))
    if severity:
        statement = statement.where(Alert.severity == severity)
    if status:
        statement = statement.where(Alert.status == status)
    rows = (
        await session.scalars(
            statement.order_by(Alert.created_at.desc()).offset(skip).limit(limit)
        )
    ).all()
    return [_serialize_alert(row) for row in rows]


@router.post("/alerts")
async def create_alert(
    title: str,
    description: str,
    severity: str = "warning",
    source: str = "monitoring",
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    alert = Alert(
        organization_id=actor.organization_id,
        title=title.strip(),
        description=description.strip(),
        severity=severity.strip(),
        status="active",
        source=source.strip(),
    )
    session.add(alert)
    await session.flush()
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="alert.create",
            resource_type="alert",
            resource_id=alert.id,
            details={"severity": alert.severity, "source": alert.source},
        )
    )
    await session.commit()
    return _serialize_alert(alert)


async def _set_alert_status(
    alert_id: str,
    new_status: str,
    actor: UserRecord,
    session: AsyncSession,
) -> dict[str, Any]:
    alert = await session.scalar(
        select(Alert).where(Alert.id == alert_id).with_for_update()
    )
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    now = datetime.now(UTC)
    alert.status = new_status
    if new_status == "acknowledged":
        alert.acknowledged_at = now
    if new_status == "resolved":
        alert.resolved_at = now
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action=f"alert.{new_status}",
            resource_type="alert",
            resource_id=alert.id,
            details={"status": new_status},
        )
    )
    await session.commit()
    return _serialize_alert(alert)


@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(
    alert_id: str,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    return await _set_alert_status(alert_id, "acknowledged", actor, session)


@router.post("/alerts/{alert_id}/resolve")
async def resolve_alert(
    alert_id: str,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    return await _set_alert_status(alert_id, "resolved", actor, session)


@router.get("/health")
async def monitoring_health(
    actor: UserRecord = Depends(require_permissions("monitoring:read")),
    session: AsyncSession = Depends(get_db),
):
    alert_statement = select(Alert).where(
        _alert_scope(actor),
        Alert.status != "resolved",
    )
    unresolved = (await session.scalars(alert_statement)).all()
    critical = [alert for alert in unresolved if alert.severity == "critical"]
    backup_count = await session.scalar(select(func.count(BackupRecord.id)))
    latest_mode_run = await session.scalar(
        select(DisasterRecoveryRun)
        .where(
            DisasterRecoveryRun.status == "completed",
            DisasterRecoveryRun.operation.in_(["failover", "failback"]),
        )
        .order_by(DisasterRecoveryRun.created_at.desc())
        .limit(1)
    )
    latest_test = await session.scalar(
        select(DisasterRecoveryRun)
        .where(
            DisasterRecoveryRun.status == "completed",
            DisasterRecoveryRun.operation == "test",
        )
        .order_by(DisasterRecoveryRun.created_at.desc())
        .limit(1)
    )
    return {
        "status": "degraded" if critical else "healthy",
        "timestamp": _iso(datetime.now(UTC)),
        "alerts_active": len(unresolved),
        "critical_alerts": len(critical),
        "backups": int(backup_count or 0),
        "dr": {
            "mode": (
                "failover"
                if latest_mode_run is not None
                and latest_mode_run.operation == "failover"
                else "standby"
            ),
            "last_test_at": (
                _iso(latest_test.completed_at or latest_test.created_at)
                if latest_test is not None
                else None
            ),
            "rpo_minutes": 15,
            "rto_minutes": 60,
        },
    }
