from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord, current_user
from app.db.base import get_db
from app.services import growth_advanced_integrations as advanced

router = APIRouter()


class IntegrationCreateRequest(BaseModel):
    integration_type: str = Field(min_length=1, max_length=32)
    provider: str = Field(default="generic", min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=160)
    credential_ref: str | None = Field(default=None, max_length=320)
    config: dict[str, Any] = Field(default_factory=dict)
    capabilities: list[str] = Field(default_factory=list)


class TeamAssignmentRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=36)
    team_id: str | None = Field(default=None, max_length=36)
    scope_type: str = Field(min_length=1, max_length=40)
    scope_id: str = Field(min_length=1, max_length=160)
    role_key: str = Field(default="viewer", max_length=32)
    permissions: list[str] = Field(default_factory=list)
    approval_required: bool = False


class TeamRoutingRequest(BaseModel):
    scope_type: str = Field(min_length=1, max_length=40)
    scope_id: str = Field(min_length=1, max_length=160)


class ReportDefinitionRequest(BaseModel):
    name: str = Field(min_length=1, max_length=180)
    report_type: str = Field(default="executive", min_length=1, max_length=40)
    formats: list[str] = Field(default_factory=lambda: ["json"])
    filters: dict[str, Any] = Field(default_factory=dict)
    schedule_kind: str = Field(default="manual", max_length=24)
    timezone: str = Field(default="UTC", max_length=80)
    brand_name: str | None = Field(default=None, max_length=180)
    custom_domain: str | None = Field(default=None, max_length=253)
    branding: dict[str, Any] = Field(default_factory=dict)


class BrandingPreviewRequest(BaseModel):
    brand_name: str | None = Field(default=None, max_length=180)
    custom_domain: str | None = Field(default=None, max_length=253)
    branding: dict[str, Any] = Field(default_factory=dict)


def _error(exc: advanced.GrowthAdvancedError) -> HTTPException:
    message = str(exc)
    if message.startswith("access-denied:"):
        return HTTPException(status_code=403, detail=message)
    if "not-found" in message:
        return HTTPException(status_code=404, detail=message)
    return HTTPException(status_code=400, detail=message)


@router.post("/integrations")
async def create_integration(
    payload: IntegrationCreateRequest,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        row = await advanced.create_integration(session, actor, payload.model_dump())
        await session.commit()
        await session.refresh(row)
        return advanced.public_integration(row)
    except advanced.GrowthAdvancedError as exc:
        await session.rollback()
        raise _error(exc) from exc


@router.get("/integrations")
async def list_integrations(
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        rows = await advanced.list_integrations(session, actor)
        return {
            "items": [advanced.public_integration(row) for row in rows],
            "external_delivery_allowed": False,
            "live_provider_call": False,
        }
    except advanced.GrowthAdvancedError as exc:
        raise _error(exc) from exc


@router.post("/integrations/{integration_id}/simulate")
async def simulate_integration(
    integration_id: str,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        evidence = await advanced.simulate_integration(session, actor, integration_id)
        await session.commit()
        return evidence
    except advanced.GrowthAdvancedError as exc:
        await session.rollback()
        raise _error(exc) from exc


@router.post("/team-assignments")
async def upsert_team_assignment(
    payload: TeamAssignmentRequest,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        row = await advanced.upsert_team_assignment(
            session, actor, payload.model_dump()
        )
        await session.commit()
        await session.refresh(row)
        return advanced.public_team_assignment(row)
    except advanced.GrowthAdvancedError as exc:
        await session.rollback()
        raise _error(exc) from exc


@router.get("/team-assignments")
async def list_team_assignments(
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        rows = await advanced.list_team_assignments(session, actor)
        return {"items": [advanced.public_team_assignment(row) for row in rows]}
    except advanced.GrowthAdvancedError as exc:
        raise _error(exc) from exc


@router.post("/team-assignments/simulate-routing")
async def simulate_team_routing(
    payload: TeamRoutingRequest,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        return await advanced.simulate_team_routing(
            session, actor, payload.scope_type, payload.scope_id
        )
    except advanced.GrowthAdvancedError as exc:
        raise _error(exc) from exc


@router.post("/reports/branding/preview")
async def branding_preview(
    payload: BrandingPreviewRequest,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        return await advanced.branding_preview_for_actor(
            session, actor, payload.model_dump()
        )
    except advanced.GrowthAdvancedError as exc:
        raise _error(exc) from exc


@router.post("/reports/simulate-due")
async def simulate_due_reports(
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        rows = await advanced.simulate_due_reports(session, actor)
        await session.commit()
        return {
            "runs": [advanced.public_report_run(row) for row in rows],
            "external_delivery_allowed": False,
            "provider_call_allowed": False,
        }
    except advanced.GrowthAdvancedError as exc:
        await session.rollback()
        raise _error(exc) from exc


@router.post("/reports")
async def create_report_definition(
    payload: ReportDefinitionRequest,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        row = await advanced.create_report_definition(
            session, actor, payload.model_dump()
        )
        await session.commit()
        await session.refresh(row)
        return advanced.public_report_definition(row)
    except advanced.GrowthAdvancedError as exc:
        await session.rollback()
        raise _error(exc) from exc


@router.get("/reports")
async def list_report_definitions(
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        rows = await advanced.list_report_definitions(session, actor)
        return {"items": [advanced.public_report_definition(row) for row in rows]}
    except advanced.GrowthAdvancedError as exc:
        raise _error(exc) from exc


@router.post("/reports/{definition_id}/run")
async def run_report(
    definition_id: str,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        row = await advanced.run_report(session, actor, definition_id)
        await session.commit()
        await session.refresh(row)
        return advanced.public_report_run(row)
    except advanced.GrowthAdvancedError as exc:
        await session.rollback()
        raise _error(exc) from exc


@router.get("/report-runs/{run_id}")
async def get_report_run(
    run_id: str,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        row = await advanced.get_report_run(session, actor, run_id)
        return advanced.public_report_run(row)
    except advanced.GrowthAdvancedError as exc:
        raise _error(exc) from exc


@router.get("/report-runs/{run_id}/artifact/{format_name}")
async def download_report_artifact(
    run_id: str,
    format_name: str,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> Response:
    try:
        data, media_type, filename = await advanced.report_artifact(
            session, actor, run_id, format_name
        )
        return Response(
            content=data,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except advanced.GrowthAdvancedError as exc:
        raise _error(exc) from exc
