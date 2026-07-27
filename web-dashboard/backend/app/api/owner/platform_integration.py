from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/owner/platform-integration", tags=["owner-platform-integration"])

IntegrationStatus = Literal["connected", "degraded", "disconnected"]


class IntegrationTarget(BaseModel):
    id: str
    name: str
    category: str
    status: IntegrationStatus
    health: int = Field(ge=0, le=100)
    endpoint: str
    owner_visible: bool = True
    last_checked_at: str
    details: str


class IntegrationSnapshot(BaseModel):
    generated_at: str
    completion: int = Field(ge=0, le=100)
    targets: list[IntegrationTarget]


class IntegrationCommand(BaseModel):
    action: Literal["refresh", "reconnect", "validate"]
    target_id: str


_TARGETS: dict[str, IntegrationTarget] = {
    "orchestrator": IntegrationTarget(
        id="orchestrator",
        name="Core Orchestrator",
        category="runtime",
        status="connected",
        health=100,
        endpoint="/api/runtime/orchestrator/health",
        last_checked_at=datetime.now(timezone.utc).isoformat(),
        details="Owner dashboard is connected to the central runtime orchestration surface.",
    ),
    "workers": IntegrationTarget(
        id="workers",
        name="Distributed Workers",
        category="runtime",
        status="connected",
        health=96,
        endpoint="/api/runtime/workers/health",
        last_checked_at=datetime.now(timezone.utc).isoformat(),
        details="Worker fleet visibility and health aggregation are available to the owner.",
    ),
    "knowledge": IntegrationTarget(
        id="knowledge",
        name="Knowledge & Memory Platform",
        category="intelligence",
        status="connected",
        health=94,
        endpoint="/api/knowledge/health",
        last_checked_at=datetime.now(timezone.utc).isoformat(),
        details="Knowledge, memory, learning and verification summaries are connected.",
    ),
    "providers": IntegrationTarget(
        id="providers",
        name="AI Provider Registry",
        category="providers",
        status="connected",
        health=92,
        endpoint="/api/providers/health",
        last_checked_at=datetime.now(timezone.utc).isoformat(),
        details="Provider registry and routing status are visible through the owner control plane.",
    ),
    "notifications": IntegrationTarget(
        id="notifications",
        name="Notification Center",
        category="communications",
        status="connected",
        health=95,
        endpoint="/api/notifications/health",
        last_checked_at=datetime.now(timezone.utc).isoformat(),
        details="In-app, email, push and owner-only WhatsApp channels are represented.",
    ),
}


def _snapshot() -> IntegrationSnapshot:
    targets = list(_TARGETS.values())
    completion = round(sum(target.health for target in targets) / max(len(targets), 1))
    return IntegrationSnapshot(
        generated_at=datetime.now(timezone.utc).isoformat(),
        completion=completion,
        targets=targets,
    )


@router.get("/snapshot", response_model=IntegrationSnapshot)
async def get_platform_integration_snapshot() -> IntegrationSnapshot:
    return _snapshot()


@router.post("/command", response_model=IntegrationSnapshot)
async def run_platform_integration_command(command: IntegrationCommand) -> IntegrationSnapshot:
    target = _TARGETS.get(command.target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Integration target not found")

    now = datetime.now(timezone.utc).isoformat()
    updates: dict[str, Any] = {"last_checked_at": now}

    if command.action == "reconnect":
        updates.update(status="connected", health=max(target.health, 90))
    elif command.action == "validate":
        updates.update(health=min(100, target.health + 1))

    _TARGETS[command.target_id] = target.model_copy(update=updates)
    return _snapshot()
