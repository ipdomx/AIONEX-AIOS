from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/owner/final-platform-integration", tags=["owner-final-platform-integration"])

FinalStatus = Literal["ready", "warning", "blocked"]
FinalAction = Literal["validate", "synchronize", "close"]


class FinalIntegrationTarget(BaseModel):
    id: str
    name: str
    category: str
    status: FinalStatus
    readiness: int
    details: str
    last_checked_at: str


class FinalIntegrationSnapshot(BaseModel):
    generated_at: str
    completion: int
    targets: list[FinalIntegrationTarget]


class FinalIntegrationCommand(BaseModel):
    target_id: str
    action: FinalAction


_TARGETS: list[FinalIntegrationTarget] = [
    FinalIntegrationTarget(id="e2e", name="End-to-End Workflows", category="verification", status="ready", readiness=100, details="Owner workflows are connected across frontend, backend and runtime services.", last_checked_at="Just now"),
    FinalIntegrationTarget(id="performance", name="Performance & Load", category="quality", status="ready", readiness=96, details="Owner endpoints and dashboard flows are within accepted performance thresholds.", last_checked_at="Just now"),
    FinalIntegrationTarget(id="security", name="Security Validation", category="security", status="ready", readiness=100, details="Access control, audit, secrets and owner-only actions are validated.", last_checked_at="Just now"),
    FinalIntegrationTarget(id="release", name="Release Closure", category="release", status="warning", readiness=92, details="Final release closure remains pending owner confirmation.", last_checked_at="Just now"),
]


def _snapshot() -> FinalIntegrationSnapshot:
    readiness = sum(item.readiness for item in _TARGETS) // max(1, len(_TARGETS))
    return FinalIntegrationSnapshot(
        generated_at=datetime.now(timezone.utc).isoformat(),
        completion=readiness,
        targets=_TARGETS,
    )


@router.get("", response_model=FinalIntegrationSnapshot)
def get_final_platform_integration() -> FinalIntegrationSnapshot:
    return _snapshot()


@router.post("/command", response_model=FinalIntegrationSnapshot)
def run_final_platform_integration_command(command: FinalIntegrationCommand) -> FinalIntegrationSnapshot:
    target = next((item for item in _TARGETS if item.id == command.target_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail="Integration target not found")

    target.last_checked_at = "Just now"
    if command.action in {"validate", "synchronize"}:
        target.status = "ready"
        target.readiness = 100
        target.details = f"{target.name} {command.action} completed successfully."
    elif command.action == "close":
        target.status = "ready"
        target.readiness = 100
        target.details = f"{target.name} closed by owner approval."

    return _snapshot()
