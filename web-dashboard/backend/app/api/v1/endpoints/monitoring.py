"""Monitoring endpoints."""

from fastapi import APIRouter, Query
from typing import List, Optional

router = APIRouter()

@router.get("/metrics")
async def get_metrics(
    metric_type: Optional[str] = None,
    resource: Optional[str] = None,
    hours: int = Query(24, ge=1, le=168),
):
    """Get system metrics."""
    return {
        "cpu": [{"timestamp": f"2024-01-15T{i:02d}:00:00Z", "value": 40 + i * 2} for i in range(hours)],
        "memory": [{"timestamp": f"2024-01-15T{i:02d}:00:00Z", "value": 50 + i} for i in range(hours)],
        "disk": [{"timestamp": f"2024-01-15T{i:02d}:00:00Z", "value": 30 + i * 0.5} for i in range(hours)],
        "network": {
            "rx": [{"timestamp": f"2024-01-15T{i:02d}:00:00Z", "value": 100 + i * 5} for i in range(hours)],
            "tx": [{"timestamp": f"2024-01-15T{i:02d}:00:00Z", "value": 80 + i * 3} for i in range(hours)],
        },
    }

@router.get("/logs")
async def get_logs(
    level: Optional[str] = None,
    service: Optional[str] = None,
    search: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
):
    """Get system logs."""
    return [
        {
            "id": f"log-{i}",
            "timestamp": "2024-01-15T10:00:00Z",
            "level": "info" if i % 4 == 0 else "warning" if i % 4 == 1 else "error" if i % 4 == 2 else "debug",
            "service": "api" if i % 3 == 0 else "worker" if i % 3 == 1 else "db",
            "message": f"Log message {i}",
            "trace_id": f"trace-{i}",
        }
        for i in range(limit)
    ]

@router.get("/alerts")
async def get_alerts(
    severity: Optional[str] = None,
    status: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
):
    """Get active alerts."""
    return [
        {
            "id": f"alert-{i}",
            "title": f"Alert {i}",
            "description": f"Alert description {i}",
            "severity": "warning" if i % 3 == 0 else "critical" if i % 3 == 1 else "info",
            "status": "active" if i % 2 == 0 else "acknowledged",
            "source": "monitoring",
            "created_at": "2024-01-15T10:00:00Z",
        }
        for i in range(limit)
    ]

@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: str):
    """Acknowledge alert."""
    return {"message": "Alert acknowledged", "alert_id": alert_id}

@router.post("/alerts/{alert_id}/resolve")
async def resolve_alert(alert_id: str):
    """Resolve alert."""
    return {"message": "Alert resolved", "alert_id": alert_id}
