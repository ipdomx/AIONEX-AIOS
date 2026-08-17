"""Production runtime readiness derived from live backend dependencies."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any, Literal

from app.api.owner.control_plane import _health_items, _run_audited_mutation
from app.core.auth import UserRecord, require_super_owner
from app.core.config import settings
from app.db.base import get_db
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.project_execution_worker import project_execution_fabric_snapshot

router = APIRouter(
    prefix="/owner/production-runtime",
    tags=["owner-production-runtime"],
)


class RuntimeTarget(BaseModel):
    id: str
    name: str
    category: str
    status: Literal["ready", "degraded", "blocked"]
    readiness: int = Field(ge=0, le=100)
    details: str
    last_checked_at: str


class RuntimeSnapshot(BaseModel):
    generated_at: str
    completion: int = Field(ge=0, le=100)
    public_origin: str
    api_origin: str
    targets: list[RuntimeTarget]


class ProjectExecutionFabricSnapshot(BaseModel):
    captured_at: str
    queued: int = Field(ge=0)
    running: int = Field(ge=0)
    retry_queued: int = Field(ge=0)
    dead_lettered: int = Field(ge=0)
    oldest_queue_wait_seconds: float = Field(ge=0)
    queue_by_resource_class: dict[str, int]
    workers_online: int = Field(ge=0)
    worker_capacity: int = Field(ge=0)
    worker_active_slots: int = Field(ge=0)
    worker_saturation: float = Field(ge=0)


def _clean_origin(value: str | None) -> str:
    raw = str(value or "").strip().rstrip("/")
    return raw or "Not configured"


def _public_origin() -> str:
    explicit = os.getenv("AIOS_PUBLIC_ORIGIN")
    if explicit:
        return _clean_origin(explicit)
    for candidate in settings.CORS_ORIGINS:
        value = str(candidate).strip()
        if value.startswith("https://"):
            return _clean_origin(value)
    return "Not configured"


def _api_origin() -> str:
    return _clean_origin(
        os.getenv("AIOS_API_ORIGIN") or settings.PORTAL_PUBLIC_API_ORIGIN
    )


class RuntimeCommand(BaseModel):
    target_id: str
    action: Literal["validate"]


async def _snapshot(session: AsyncSession) -> RuntimeSnapshot:
    health = await _health_items(session)
    now = datetime.now(UTC).isoformat()
    targets = [
        RuntimeTarget(
            id=item["id"],
            name=item["name"],
            category="runtime",
            status=(
                "ready"
                if item["status"] == "healthy"
                else (
                    "degraded"
                    if item["status"] in {"degraded", "warning"}
                    else "blocked"
                )
            ),
            readiness=(
                100
                if item["status"] == "healthy"
                else 60 if item["status"] in {"degraded", "warning"} else 0
            ),
            details=item["detail"],
            last_checked_at=now,
        )
        for item in health
    ]
    completion = round(sum(item.readiness for item in targets) / max(1, len(targets)))
    return RuntimeSnapshot(
        generated_at=now,
        completion=completion,
        public_origin=_public_origin(),
        api_origin=_api_origin(),
        targets=targets,
    )


@router.get("", response_model=RuntimeSnapshot)
async def get_runtime_snapshot(
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> RuntimeSnapshot:
    return await _snapshot(session)


@router.get("/project-execution-fabric", response_model=ProjectExecutionFabricSnapshot)
async def get_project_execution_fabric(
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> ProjectExecutionFabricSnapshot:
    snapshot = await project_execution_fabric_snapshot(session)
    return ProjectExecutionFabricSnapshot.model_validate(snapshot)


@router.post("/command", response_model=RuntimeSnapshot)
async def run_runtime_command(
    command: RuntimeCommand,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> RuntimeSnapshot:
    async def validate(_audit: object) -> dict[str, Any]:
        snapshot = await _snapshot(session)
        if not any(target.id == command.target_id for target in snapshot.targets):
            raise HTTPException(
                status_code=404,
                detail="Production runtime target not found",
            )
        target = next(item for item in snapshot.targets if item.id == command.target_id)
        if target.status != "ready":
            raise HTTPException(
                status_code=503,
                detail=f"{target.name} is not production ready",
            )
        return {
            "health_rechecked": True,
            "status": target.status,
            "readiness": target.readiness,
        }

    await _run_audited_mutation(
        session,
        actor=actor,
        domain="production-runtime",
        resource_id=command.target_id,
        action=command.action,
        request=command.model_dump(mode="json"),
        mutation=validate,
    )
    return await _snapshot(session)
