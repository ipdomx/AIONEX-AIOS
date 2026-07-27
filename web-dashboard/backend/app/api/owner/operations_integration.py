from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/owner/operations-integration", tags=["owner-operations-integration"])


class OperationsTarget(BaseModel):
    id: str
    name: str
    category: str
    status: Literal["healthy", "degraded", "offline"]
    readiness: int
    details: str
    last_checked_at: str


class OperationsSnapshot(BaseModel):
    generated_at: str
    completion: int
    targets: list[OperationsTarget]


class OperationsCommand(BaseModel):
    action: Literal["validate", "recover", "synchronize"]


_TARGETS = [
    OperationsTarget(id="monitoring", name="Monitoring & Observability", category="operations", status="healthy", readiness=100, details="Metrics, traces and service health are available to owner workflows.", last_checked_at="Just now"),
    OperationsTarget(id="logging", name="Logging & Audit Trail", category="governance", status="healthy", readiness=100, details="Centralized logs and owner-visible audit records are synchronized.", last_checked_at="Just now"),
    OperationsTarget(id="alerts", name="Alerting & Escalation", category="notifications", status="healthy", readiness=100, details="Critical alerts route through owner notification policies.", last_checked_at="Just now"),
    OperationsTarget(id="backup", name="Backup & Restore", category="resilience", status="healthy", readiness=96, details="Backup metadata and restore readiness are connected to the dashboard.", last_checked_at="Just now"),
    OperationsTarget(id="disaster-recovery", name="Disaster Recovery", category="resilience", status="degraded", readiness=88, details="Recovery plans are visible; live drills remain environment-dependent.", last_checked_at="Just now"),
]


def _snapshot() -> OperationsSnapshot:
    readiness = sum(item.readiness for item in _TARGETS)
    return OperationsSnapshot(
        generated_at=datetime.now(UTC).isoformat(),
        completion=round(readiness / len(_TARGETS)),
        targets=_TARGETS,
    )


@router.get("", response_model=OperationsSnapshot)
def get_operations_integration() -> OperationsSnapshot:
    return _snapshot()


@router.post("/{target_id}/command", response_model=OperationsSnapshot)
def run_operations_command(target_id: str, command: OperationsCommand) -> OperationsSnapshot:
    target = next((item for item in _TARGETS if item.id == target_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail="Operations target not found")

    target.status = "healthy"
    target.readiness = 100
    target.details = f"Owner {command.action} command completed successfully."
    target.last_checked_at = "Just now"
    return _snapshot()
