"""Final platform integration checks derived from live Owner readiness."""

from datetime import UTC, datetime
from typing import Any, Literal

from app.api.owner.control_plane import (
    _apply_live_action,
    _control_items,
    _control_record,
    _health_items,
    _revalidate_non_owner_release_gates,
    _run_audited_mutation,
)
from app.core.auth import UserRecord, require_super_owner
from app.db.base import get_db
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(
    prefix="/owner/final-platform-integration",
    tags=["owner-final-platform-integration"],
)


class FinalIntegrationTarget(BaseModel):
    id: str
    name: str
    category: str
    status: Literal["ready", "warning", "blocked"]
    readiness: int
    details: str
    last_checked_at: str


class FinalIntegrationSnapshot(BaseModel):
    generated_at: str
    completion: int
    closed: bool
    state: Literal["open", "closed"]
    closed_at: str | None = None
    closed_by: str | None = None
    targets: list[FinalIntegrationTarget]


class FinalIntegrationCommand(BaseModel):
    target_id: str
    action: Literal["validate", "close"]


async def _snapshot(session: AsyncSession) -> FinalIntegrationSnapshot:
    health = await _health_items(session)
    all_release_gates = await _control_items(session, "release")
    approval = next(
        (item for item in all_release_gates if item["id"] == "approval"),
        {},
    )
    release_gates = await _revalidate_non_owner_release_gates(session)
    closed_at = approval.get("platformClosedAt")
    closed = bool(closed_at)
    now = datetime.now(UTC).isoformat()
    targets = [
        FinalIntegrationTarget(
            id=item["id"],
            name=item["name"],
            category="integration",
            status=(
                "ready"
                if item["status"] == "healthy"
                else (
                    "warning"
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
    release_ready = bool(release_gates) and all(
        item["status"] == "passed" for item in release_gates
    )
    targets.append(
        FinalIntegrationTarget(
            id="release-governance",
            name="Release Governance",
            category="release",
            status="ready" if release_ready else "blocked",
            readiness=100 if release_ready else 0,
            details=(
                "All live non-owner release gates passed."
                if release_ready
                else "Run live release validation before closure."
            ),
            last_checked_at=now,
        )
    )
    completion = round(sum(item.readiness for item in targets) / max(1, len(targets)))
    return FinalIntegrationSnapshot(
        generated_at=now,
        completion=completion,
        closed=closed,
        state="closed" if closed else "open",
        closed_at=str(closed_at) if closed_at else None,
        closed_by=(
            str(approval.get("platformClosedBy"))
            if approval.get("platformClosedBy")
            else None
        ),
        targets=targets,
    )


@router.get("", response_model=FinalIntegrationSnapshot)
async def get_final_platform_integration(
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> FinalIntegrationSnapshot:
    return await _snapshot(session)


@router.post("/command", response_model=FinalIntegrationSnapshot)
async def run_final_platform_integration_command(
    command: FinalIntegrationCommand,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> FinalIntegrationSnapshot:
    async def execute(_audit: object) -> dict[str, Any]:
        if command.action == "validate":
            snapshot = await _snapshot(session)
            target = next(
                (item for item in snapshot.targets if item.id == command.target_id),
                None,
            )
            if target is None:
                raise HTTPException(
                    status_code=404,
                    detail="Integration target not found",
                )
            if target.id == "release-governance":
                gates = await _revalidate_non_owner_release_gates(session)
                blockers = [
                    item["name"] for item in gates if item["status"] != "passed"
                ]
                if blockers:
                    raise HTTPException(
                        status_code=409,
                        detail="Release validation failed: " + ", ".join(blockers),
                    )
            elif target.status != "ready":
                raise HTTPException(
                    status_code=503,
                    detail=f"{target.name} is not ready",
                )
            return {
                "target_id": target.id,
                "validated": True,
                "snapshot": (await _snapshot(session)).model_dump(mode="json"),
            }

        approval = await _control_record(session, "release", "approval")
        if approval.payload.get("platformClosedAt"):
            raise HTTPException(
                status_code=409,
                detail="Final platform readiness is already closed",
            )
        approval_result = await _apply_live_action(
            session,
            actor,
            "release",
            "approval",
            "approve",
            {},
        )
        closed_at = datetime.now(UTC).isoformat()
        approval.payload = {
            **approval.payload,
            "platformClosedAt": closed_at,
            "platformClosedBy": actor.id,
        }
        approval.version += 1
        return {
            "closed": True,
            "closed_at": closed_at,
            "release_approval": approval_result,
            "snapshot": (await _snapshot(session)).model_dump(mode="json"),
        }

    result = await _run_audited_mutation(
        session,
        actor=actor,
        domain="final-platform-integration",
        resource_id=command.target_id,
        action=command.action,
        request=command.model_dump(mode="json"),
        mutation=execute,
    )
    return FinalIntegrationSnapshot.model_validate(result["snapshot"])
