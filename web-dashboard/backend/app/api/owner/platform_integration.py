"""Live platform-integration status backed by durable owner configuration."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from app.api.owner.control_plane import (
    _apply_live_action,
    _integration_items,
    _run_audited_mutation,
)
from app.core.auth import UserRecord, require_super_owner
from app.db.base import get_db
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(
    prefix="/owner/platform-integration",
    tags=["owner-platform-integration"],
)


class IntegrationTarget(BaseModel):
    id: str
    name: str
    category: str
    status: Literal["connected", "degraded", "disconnected"]
    health: int = Field(ge=0, le=100)
    endpoint: str
    owner_visible: bool = True
    configured: bool
    last_checked_at: str
    details: str


class IntegrationSnapshot(BaseModel):
    generated_at: str
    completion: int = Field(ge=0, le=100)
    targets: list[IntegrationTarget]


class IntegrationCommand(BaseModel):
    action: Literal["validate"]
    target_id: str


async def _snapshot(session: AsyncSession) -> IntegrationSnapshot:
    records = await _integration_items(session)
    targets: list[IntegrationTarget] = []
    for item in records:
        raw_status = str(item.get("status", "unconfigured"))
        connected = bool(item.get("enabled")) and raw_status == "connected"
        status: Literal["connected", "degraded", "disconnected"] = (
            "connected"
            if connected
            else (
                "degraded"
                if bool(item.get("enabled")) and bool(item.get("configured"))
                else "disconnected"
            )
        )
        health = 100 if connected else 50 if status == "degraded" else 0
        targets.append(
            IntegrationTarget(
                id=item["id"],
                name=str(item.get("name", item["id"])),
                category=str(item.get("category", "platform")),
                status=status,
                health=health,
                endpoint=str(item.get("endpoint", "Not configured")),
                configured=bool(item.get("configured")),
                last_checked_at=str(item.get("lastCheck", item["updatedAt"])),
                details=(
                    "Connected and validated by a live dependency probe."
                    if connected
                    else (
                        "Credentials are configured; external reachability is not asserted."
                        if item.get("configured")
                        else "Deployment credentials are not configured."
                    )
                ),
            )
        )
    completion = round(sum(target.health for target in targets) / max(1, len(targets)))
    return IntegrationSnapshot(
        generated_at=datetime.now(UTC).isoformat(),
        completion=completion,
        targets=targets,
    )


@router.get("/snapshot", response_model=IntegrationSnapshot)
async def get_platform_integration_snapshot(
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> IntegrationSnapshot:
    return await _snapshot(session)


@router.post("/command", response_model=IntegrationSnapshot)
async def run_platform_integration_command(
    command: IntegrationCommand,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> IntegrationSnapshot:
    async def validate(_audit: object) -> dict[str, Any]:
        records = await _integration_items(session)
        target = next(
            (item for item in records if item["id"] == command.target_id),
            None,
        )
        if target is None:
            raise HTTPException(
                status_code=404,
                detail="Integration target not found",
            )
        if not target.get("configured"):
            raise HTTPException(
                status_code=409,
                detail="Configure deployment credentials before validation",
            )
        await _apply_live_action(
            session,
            actor,
            "integrations",
            command.target_id,
            "health-check",
            {},
        )
        return {"checked": True, "target_id": command.target_id}

    await _run_audited_mutation(
        session,
        actor=actor,
        domain="integrations",
        resource_id=command.target_id,
        action=command.action,
        request=command.model_dump(mode="json"),
        mutation=validate,
    )
    return await _snapshot(session)
