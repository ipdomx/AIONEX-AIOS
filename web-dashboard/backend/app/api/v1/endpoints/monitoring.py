"""Monitoring and observability endpoints."""
from fastapi import APIRouter, HTTPException, Query
from typing import Optional

from app.core.production_runtime import production_runtime

router = APIRouter()


@router.get("/metrics")
async def get_metrics(metric_type: Optional[str] = None, resource: Optional[str] = None, hours: int = Query(24, ge=1, le=168)):
    if metric_type:
        return {metric_type: production_runtime.metrics.get(metric_type, [])[-hours:]}
    return {name: values[-hours:] for name, values in production_runtime.metrics.items()}


@router.post("/metrics/{metric_name}")
async def record_metric(metric_name: str, value: float):
    return production_runtime.record_metric(metric_name, value)


@router.get("/logs")
async def get_logs(level: Optional[str] = None, service: Optional[str] = None, search: Optional[str] = None, skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500)):
    items = list(reversed(production_runtime.logs))
    if level:
        items = [item for item in items if item["level"] == level]
    if service:
        items = [item for item in items if item["service"] == service]
    if search:
        needle = search.lower()
        items = [item for item in items if needle in item["message"].lower()]
    return items[skip:skip + limit]


@router.post("/logs")
async def create_log(level: str, service: str, message: str, trace_id: str | None = None):
    return production_runtime.log(level, service, message, trace_id)


@router.get("/alerts")
async def get_alerts(severity: Optional[str] = None, status: Optional[str] = None, skip: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100)):
    items = [alert.__dict__.copy() for alert in production_runtime.alerts.values()]
    if severity:
        items = [item for item in items if item["severity"] == severity]
    if status:
        items = [item for item in items if item["status"] == status]
    items.sort(key=lambda item: item["created_at"], reverse=True)
    return items[skip:skip + limit]


@router.post("/alerts")
async def create_alert(title: str, description: str, severity: str = "warning", source: str = "monitoring"):
    return production_runtime.create_alert(title, description, severity, source)


@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: str):
    if alert_id not in production_runtime.alerts:
        raise HTTPException(status_code=404, detail="Alert not found")
    return production_runtime.set_alert_status(alert_id, "acknowledged")


@router.post("/alerts/{alert_id}/resolve")
async def resolve_alert(alert_id: str):
    if alert_id not in production_runtime.alerts:
        raise HTTPException(status_code=404, detail="Alert not found")
    return production_runtime.set_alert_status(alert_id, "resolved")


@router.get("/health")
async def monitoring_health():
    return production_runtime.health()
