"""Phase 36K professional evidence and high-stakes human review API."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord, require_permissions
from app.db.base import get_db
from app.db.models import ProfessionalEvidenceCase, ProfessionalReviewDecision
from app.services import professional_evidence

router = APIRouter()


class CitationInput(BaseModel):
    citation_id: str = Field(min_length=2, max_length=80)
    title: str = Field(min_length=2, max_length=400)
    uri: str = Field(min_length=5, max_length=1200)
    source_sha256: str = Field(min_length=64, max_length=64)


class ProfessionalCaseCreate(BaseModel):
    workspace_id: str | None = None
    case_mode: str = Field(min_length=4, max_length=40)
    purpose: str = Field(min_length=4, max_length=2000)
    subject_reference: str = Field(min_length=2, max_length=500)
    request_summary: str = Field(min_length=4, max_length=12000)
    direct_identifiers_removed: bool
    residency_profile: str = Field(
        default="tenant-default", min_length=3, max_length=120
    )
    retention_days: int | None = Field(default=None, ge=1, le=3650)
    citations: list[CitationInput] = Field(min_length=1, max_length=64)


class ProfessionalReviewCreate(BaseModel):
    decision: str = Field(min_length=4, max_length=32)
    rationale: str = Field(min_length=4, max_length=4000)


async def _case(
    session: AsyncSession, actor: UserRecord, case_id: str, *, for_update: bool = False
) -> ProfessionalEvidenceCase:
    statement = select(ProfessionalEvidenceCase).where(
        ProfessionalEvidenceCase.id == case_id,
        ProfessionalEvidenceCase.organization_id == actor.organization_id,
    )
    if for_update:
        statement = statement.with_for_update()
    item = await session.scalar(statement)
    if item is None:
        raise HTTPException(
            status_code=404, detail="Professional evidence case not found"
        )
    return item


@router.get("/profiles")
async def protected_data_profiles(
    actor: UserRecord = Depends(require_permissions("governance:read")),
):
    _ = actor
    return {
        "profiles": professional_evidence.RESIDENCY_PROFILES,
        "certification_claim": False,
        "local_legal_validation_required": True,
        "autonomous_high_stakes_decisions": False,
    }


@router.get("/cases")
async def list_cases(
    status_filter: str | None = Query(default=None, alias="status", max_length=32),
    mode: str | None = Query(default=None, max_length=40),
    limit: int = Query(default=200, ge=1, le=1000),
    actor: UserRecord = Depends(require_permissions("governance:read")),
    session: AsyncSession = Depends(get_db),
):
    statement = select(ProfessionalEvidenceCase).where(
        ProfessionalEvidenceCase.organization_id == actor.organization_id
    )
    if status_filter:
        statement = statement.where(ProfessionalEvidenceCase.status == status_filter)
    if mode:
        statement = statement.where(ProfessionalEvidenceCase.case_mode == mode)
    rows = list(
        (
            await session.scalars(
                statement.order_by(ProfessionalEvidenceCase.created_at.desc()).limit(
                    limit
                )
            )
        ).all()
    )
    return [professional_evidence.case_snapshot(item) for item in rows]


@router.post("/cases", status_code=status.HTTP_201_CREATED)
async def create_case(
    data: ProfessionalCaseCreate,
    actor: UserRecord = Depends(require_permissions("governance:write")),
    session: AsyncSession = Depends(get_db),
):
    try:
        item = await professional_evidence.create_case(
            session,
            actor,
            workspace_id=data.workspace_id,
            case_mode=data.case_mode,
            purpose=data.purpose,
            subject_reference=data.subject_reference,
            request_summary=data.request_summary,
            direct_identifiers_removed=data.direct_identifiers_removed,
            residency_profile=data.residency_profile,
            retention_days=data.retention_days,
            citations=[item.model_dump() for item in data.citations],
        )
        await session.commit()
        await session.refresh(item)
    except LookupError as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return professional_evidence.case_snapshot(item)


@router.get("/cases/{case_id}")
async def get_case(
    case_id: str,
    actor: UserRecord = Depends(require_permissions("governance:read")),
    session: AsyncSession = Depends(get_db),
):
    item = await _case(session, actor, case_id)
    reviews = list(
        (
            await session.scalars(
                select(ProfessionalReviewDecision)
                .where(
                    ProfessionalReviewDecision.case_id == item.id,
                    ProfessionalReviewDecision.organization_id == actor.organization_id,
                )
                .order_by(ProfessionalReviewDecision.review_version)
            )
        ).all()
    )
    return {
        **professional_evidence.case_snapshot(item),
        "reviews": [professional_evidence.review_snapshot(row) for row in reviews],
    }


@router.post("/cases/{case_id}/review")
async def review_case(
    case_id: str,
    data: ProfessionalReviewCreate,
    actor: UserRecord = Depends(require_permissions("governance:approve")),
    session: AsyncSession = Depends(get_db),
):
    item = await _case(session, actor, case_id, for_update=True)
    try:
        review = await professional_evidence.review_case(
            session, actor, item, decision=data.decision, rationale=data.rationale
        )
        await session.commit()
        await session.refresh(item)
        await session.refresh(review)
    except (PermissionError, ValueError) as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "case": professional_evidence.case_snapshot(item),
        "review": professional_evidence.review_snapshot(review),
    }


@router.post("/cases/{case_id}/close")
async def close_case(
    case_id: str,
    actor: UserRecord = Depends(require_permissions("governance:approve")),
    session: AsyncSession = Depends(get_db),
):
    item = await _case(session, actor, case_id, for_update=True)
    try:
        await professional_evidence.close_case(session, actor, item)
        await session.commit()
        await session.refresh(item)
    except (PermissionError, ValueError) as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return professional_evidence.case_snapshot(item)
