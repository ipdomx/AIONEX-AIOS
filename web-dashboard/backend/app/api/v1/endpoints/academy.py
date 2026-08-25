"""Tenant-scoped academy, assessments, and certifications for Phase 29F."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from pathlib import Path
import os
import json

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord, require_permissions
from app.db.base import get_db
from app.db.models import (
    AcademyCertification,
    AcademyCourse,
    AcademyCoursePackage,
    AcademyEnrollment,
    WorkforceMember,
)
from app.services import workforce
from app.services import academy_course_runtime

router = APIRouter()


class CourseCreate(BaseModel):
    code: str = Field(min_length=2, max_length=120)
    title: str = Field(min_length=2, max_length=240)
    description: str | None = Field(default=None, max_length=20000)
    competencies: list[str] = Field(default_factory=list, max_length=200)
    passing_score: float = Field(default=80, ge=0, le=100)


class EnrollmentCreate(BaseModel):
    worker_id: str
    due_at: datetime | None = None


class AssessmentCreate(BaseModel):
    score: float = Field(ge=0, le=100)
    evidence: dict[str, Any] = Field(default_factory=dict)


class CourseCitationInput(BaseModel):
    citation_id: str = Field(min_length=2, max_length=64)
    title: str = Field(min_length=2, max_length=300)
    uri: str = Field(min_length=5, max_length=1000)
    author: str | None = Field(default=None, max_length=200)


class CoursePackageCreate(BaseModel):
    idempotency_key: str = Field(min_length=4, max_length=160)
    domain: str = Field(min_length=2, max_length=240)
    audience: str = Field(min_length=2, max_length=240)
    locales: list[str] = Field(
        default_factory=lambda: ["ar", "en", "fr", "de", "es", "tr"],
        min_length=1,
        max_length=6,
    )
    module_count: int = Field(default=2, ge=1, le=8)
    lessons_per_module: int = Field(default=2, ge=1, le=8)
    citations: list[CourseCitationInput] = Field(default_factory=list, max_length=64)


class CoursePackageReview(BaseModel):
    approved: bool
    notes: str = Field(default="", max_length=4000)


class LessonProgressUpdate(BaseModel):
    locale: str = Field(default="en", min_length=2, max_length=8)
    progress_percent: float = Field(ge=0, le=100)
    score: float | None = Field(default=None, ge=0, le=100)
    position: dict[str, Any] = Field(default_factory=dict)


class CertificationRevoke(BaseModel):
    reason: str = Field(min_length=2, max_length=2000)


async def _course(
    session: AsyncSession,
    actor: UserRecord,
    course_id: str,
    *,
    for_update: bool = False,
) -> AcademyCourse:
    statement = select(AcademyCourse).where(
        AcademyCourse.id == course_id,
        AcademyCourse.organization_id == actor.organization_id,
    )
    if for_update:
        statement = statement.with_for_update()
    item = await session.scalar(statement)
    if item is None:
        raise HTTPException(status_code=404, detail="Academy course not found")
    return item


async def _enrollment(
    session: AsyncSession,
    actor: UserRecord,
    enrollment_id: str,
    *,
    for_update: bool = False,
) -> AcademyEnrollment:
    statement = select(AcademyEnrollment).where(
        AcademyEnrollment.id == enrollment_id,
        AcademyEnrollment.organization_id == actor.organization_id,
    )
    if for_update:
        statement = statement.with_for_update()
    item = await session.scalar(statement)
    if item is None:
        raise HTTPException(status_code=404, detail="Academy enrollment not found")
    return item


async def _certification(
    session: AsyncSession,
    actor: UserRecord,
    certification_id: str,
    *,
    for_update: bool = False,
) -> AcademyCertification:
    statement = select(AcademyCertification).where(
        AcademyCertification.id == certification_id,
        AcademyCertification.organization_id == actor.organization_id,
    )
    if for_update:
        statement = statement.with_for_update()
    item = await session.scalar(statement)
    if item is None:
        raise HTTPException(status_code=404, detail="Academy certification not found")
    return item


@router.get("/courses")
async def list_courses(
    status_filter: str | None = Query(default=None, alias="status", max_length=32),
    search: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=200, ge=1, le=1000),
    actor: UserRecord = Depends(require_permissions("academy:read")),
    session: AsyncSession = Depends(get_db),
):
    statement = select(AcademyCourse).where(
        AcademyCourse.organization_id == actor.organization_id
    )
    if status_filter:
        statement = statement.where(AcademyCourse.status == status_filter)
    if search:
        normalized = search.strip()
        statement = statement.where(
            AcademyCourse.title.ilike(f"%{normalized}%")
            | AcademyCourse.code.ilike(f"%{normalized}%")
        )
    rows = list(
        (
            await session.scalars(statement.order_by(AcademyCourse.title).limit(limit))
        ).all()
    )
    return [workforce.course_snapshot(item) for item in rows]


@router.post("/courses", status_code=status.HTTP_201_CREATED)
async def create_course(
    data: CourseCreate,
    actor: UserRecord = Depends(require_permissions("academy:write")),
    session: AsyncSession = Depends(get_db),
):
    try:
        item = await workforce.create_course(
            session,
            actor,
            code=data.code,
            title=data.title,
            description=data.description,
            competencies=data.competencies,
            passing_score=data.passing_score,
        )
        await session.commit()
        await session.refresh(item)
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return workforce.course_snapshot(item)


@router.get("/courses/{course_id}")
async def get_course(
    course_id: str,
    actor: UserRecord = Depends(require_permissions("academy:read")),
    session: AsyncSession = Depends(get_db),
):
    return workforce.course_snapshot(await _course(session, actor, course_id))


@router.post("/courses/{course_id}/enroll", status_code=status.HTTP_201_CREATED)
async def enroll_member(
    course_id: str,
    data: EnrollmentCreate,
    actor: UserRecord = Depends(require_permissions("academy:write")),
    session: AsyncSession = Depends(get_db),
):
    course = await _course(session, actor, course_id)
    member = await session.scalar(
        select(WorkforceMember).where(
            WorkforceMember.id == data.worker_id,
            WorkforceMember.organization_id == actor.organization_id,
            WorkforceMember.status != "retired",
        )
    )
    if member is None:
        raise HTTPException(status_code=404, detail="Workforce member not found")
    try:
        item = await workforce.enroll_member(
            session,
            actor,
            course,
            member,
            due_at=data.due_at,
        )
        await session.commit()
        await session.refresh(item)
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return workforce.enrollment_snapshot(item)


@router.get("/enrollments")
async def list_enrollments(
    worker_id: str | None = None,
    course_id: str | None = None,
    status_filter: str | None = Query(default=None, alias="status", max_length=32),
    limit: int = Query(default=200, ge=1, le=1000),
    actor: UserRecord = Depends(require_permissions("academy:read")),
    session: AsyncSession = Depends(get_db),
):
    statement = select(AcademyEnrollment).where(
        AcademyEnrollment.organization_id == actor.organization_id
    )
    if worker_id:
        statement = statement.where(AcademyEnrollment.worker_id == worker_id)
    if course_id:
        statement = statement.where(AcademyEnrollment.course_id == course_id)
    if status_filter:
        statement = statement.where(AcademyEnrollment.status == status_filter)
    rows = list(
        (
            await session.scalars(
                statement.order_by(AcademyEnrollment.created_at.desc()).limit(limit)
            )
        ).all()
    )
    return [workforce.enrollment_snapshot(item) for item in rows]


@router.get("/enrollments/{enrollment_id}")
async def get_enrollment(
    enrollment_id: str,
    actor: UserRecord = Depends(require_permissions("academy:read")),
    session: AsyncSession = Depends(get_db),
):
    return workforce.enrollment_snapshot(
        await _enrollment(session, actor, enrollment_id)
    )


@router.post("/enrollments/{enrollment_id}/assess", status_code=status.HTTP_201_CREATED)
async def assess_enrollment(
    enrollment_id: str,
    data: AssessmentCreate,
    actor: UserRecord = Depends(require_permissions("academy:assess")),
    session: AsyncSession = Depends(get_db),
):
    enrollment = await _enrollment(session, actor, enrollment_id, for_update=True)
    try:
        assessment, certification = await workforce.assess_enrollment(
            session,
            actor,
            enrollment,
            score=data.score,
            evidence=data.evidence,
        )
        await session.commit()
    except LookupError as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "assessment": workforce.assessment_snapshot(assessment),
        "certification": (
            workforce.certification_snapshot(certification)
            if certification is not None
            else None
        ),
        "enrollment": workforce.enrollment_snapshot(enrollment),
    }


@router.get("/certifications")
async def list_certifications(
    worker_id: str | None = None,
    status_filter: str | None = Query(default=None, alias="status", max_length=32),
    limit: int = Query(default=200, ge=1, le=1000),
    actor: UserRecord = Depends(require_permissions("academy:read")),
    session: AsyncSession = Depends(get_db),
):
    statement = select(AcademyCertification).where(
        AcademyCertification.organization_id == actor.organization_id
    )
    if worker_id:
        statement = statement.where(AcademyCertification.worker_id == worker_id)
    if status_filter:
        statement = statement.where(AcademyCertification.status == status_filter)
    rows = list(
        (
            await session.scalars(
                statement.order_by(AcademyCertification.issued_at.desc()).limit(limit)
            )
        ).all()
    )
    return [workforce.certification_snapshot(item) for item in rows]


@router.post("/certifications/{certification_id}/revoke")
async def revoke_certification(
    certification_id: str,
    data: CertificationRevoke,
    actor: UserRecord = Depends(require_permissions("academy:assess")),
    session: AsyncSession = Depends(get_db),
):
    item = await _certification(session, actor, certification_id, for_update=True)
    await workforce.revoke_certification(
        session,
        actor,
        item,
        reason=data.reason,
    )
    await session.commit()
    return workforce.certification_snapshot(item)


@router.post("/courses/{course_id}/packages", status_code=status.HTTP_202_ACCEPTED)
async def create_course_package(
    course_id: str,
    data: CoursePackageCreate,
    actor: UserRecord = Depends(require_permissions("academy:write")),
    session: AsyncSession = Depends(get_db),
):
    course = await _course(session, actor, course_id)
    try:
        item = await academy_course_runtime.create_package_job(
            session,
            actor,
            course,
            idempotency_key=data.idempotency_key,
            domain=data.domain,
            audience=data.audience,
            locales=data.locales,
            module_count=data.module_count,
            lessons_per_module=data.lessons_per_module,
            citations=[value.model_dump() for value in data.citations],
        )
        await session.commit()
        await session.refresh(item)
    except (ValueError, PermissionError) as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return academy_course_runtime.package_snapshot(item)


@router.get("/courses/{course_id}/packages")
async def list_course_packages(
    course_id: str,
    actor: UserRecord = Depends(require_permissions("academy:read")),
    session: AsyncSession = Depends(get_db),
):
    await _course(session, actor, course_id)
    rows = list(
        (
            await session.scalars(
                select(AcademyCoursePackage)
                .where(
                    AcademyCoursePackage.organization_id == actor.organization_id,
                    AcademyCoursePackage.course_id == course_id,
                )
                .order_by(AcademyCoursePackage.version.desc())
            )
        ).all()
    )
    return [academy_course_runtime.package_snapshot(row) for row in rows]


async def _package(
    session: AsyncSession,
    actor: UserRecord,
    package_id: str,
    *,
    for_update: bool = False,
) -> AcademyCoursePackage:
    statement = select(AcademyCoursePackage).where(
        AcademyCoursePackage.id == package_id,
        AcademyCoursePackage.organization_id == actor.organization_id,
    )
    if for_update:
        statement = statement.with_for_update()
    item = await session.scalar(statement)
    if item is None:
        raise HTTPException(status_code=404, detail="Course package not found")
    return item


@router.get("/packages/{package_id}")
async def get_course_package(
    package_id: str,
    actor: UserRecord = Depends(require_permissions("academy:read")),
    session: AsyncSession = Depends(get_db),
):
    return academy_course_runtime.package_snapshot(
        await _package(session, actor, package_id)
    )


@router.post("/packages/{package_id}/review")
async def review_course_package(
    package_id: str,
    data: CoursePackageReview,
    actor: UserRecord = Depends(require_permissions("academy:assess")),
    session: AsyncSession = Depends(get_db),
):
    item = await _package(session, actor, package_id, for_update=True)
    try:
        await academy_course_runtime.review_package(
            session, actor, item, approved=data.approved, notes=data.notes
        )
        await session.commit()
        await session.refresh(item)
    except (ValueError, PermissionError) as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return academy_course_runtime.package_snapshot(item)


@router.get("/packages/{package_id}/download")
async def download_course_package(
    package_id: str,
    actor: UserRecord = Depends(require_permissions("academy:read")),
    session: AsyncSession = Depends(get_db),
):
    item = await _package(session, actor, package_id)
    if item.status not in {"review_pending", "approved"}:
        raise HTTPException(
            status_code=409, detail="Course package is not downloadable"
        )
    try:
        path = academy_course_runtime.resolve_package_path(
            Path(
                os.getenv(
                    "ACADEMY_COURSE_PACKAGE_ROOT", "/var/lib/aionex/course-packages"
                )
            ),
            item.archive_relpath,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if (
        item.archive_sha256
        and academy_course_runtime.sha256_file(path) != item.archive_sha256
    ):
        raise HTTPException(
            status_code=409, detail="Course package integrity check failed"
        )
    return FileResponse(
        path,
        media_type="application/zip",
        filename=f"{item.course_id}-v{item.version}.zip",
    )


@router.get("/packages/{package_id}/site/{asset_path:path}")
async def course_package_site(
    package_id: str,
    asset_path: str,
    actor: UserRecord = Depends(require_permissions("academy:read")),
    session: AsyncSession = Depends(get_db),
):
    if asset_path.strip().lstrip("/").startswith("_private/"):
        raise HTTPException(status_code=404, detail="Course asset not found")
    item = await _package(session, actor, package_id)
    if item.status not in {"review_pending", "approved"} or not item.site_relpath:
        raise HTTPException(status_code=409, detail="Course site is unavailable")
    try:
        path = academy_course_runtime.resolve_package_path(
            Path(
                os.getenv(
                    "ACADEMY_COURSE_PACKAGE_ROOT", "/var/lib/aionex/course-packages"
                )
            ),
            f"{item.site_relpath}/{asset_path}",
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path)


@router.get("/packages/{package_id}/teacher/answer-key")
async def teacher_answer_key(
    package_id: str,
    actor: UserRecord = Depends(require_permissions("academy:assess")),
    session: AsyncSession = Depends(get_db),
):
    item = await _package(session, actor, package_id)
    if (
        item.status not in {"review_pending", "approved", "rejected"}
        or not item.site_relpath
    ):
        raise HTTPException(status_code=409, detail="Course answer key is unavailable")
    try:
        path = academy_course_runtime.resolve_package_path(
            Path(
                os.getenv(
                    "ACADEMY_COURSE_PACKAGE_ROOT", "/var/lib/aionex/course-packages"
                )
            ),
            f"{item.site_relpath}/_private/teacher/answer-key.json",
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return json.loads(path.read_text(encoding="utf-8"))


@router.put(
    "/enrollments/{enrollment_id}/packages/{package_id}/lessons/{lesson_key}/progress"
)
async def update_lesson_progress(
    enrollment_id: str,
    package_id: str,
    lesson_key: str,
    data: LessonProgressUpdate,
    actor: UserRecord = Depends(require_permissions("academy:read")),
    session: AsyncSession = Depends(get_db),
):
    enrollment = await _enrollment(session, actor, enrollment_id, for_update=True)
    package = await _package(session, actor, package_id)
    try:
        item = await academy_course_runtime.update_progress(
            session,
            actor,
            enrollment=enrollment,
            package=package,
            lesson_key=lesson_key,
            locale=data.locale,
            progress_percent=data.progress_percent,
            score=data.score,
            position=data.position,
        )
        await session.commit()
        await session.refresh(item)
    except (ValueError, PermissionError) as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return academy_course_runtime.progress_snapshot(item)


@router.get("/courses/{course_id}/analytics")
async def course_analytics(
    course_id: str,
    actor: UserRecord = Depends(require_permissions("academy:read")),
    session: AsyncSession = Depends(get_db),
):
    await _course(session, actor, course_id)
    return await academy_course_runtime.analytics_snapshot(
        session, organization_id=actor.organization_id, course_id=course_id
    )
