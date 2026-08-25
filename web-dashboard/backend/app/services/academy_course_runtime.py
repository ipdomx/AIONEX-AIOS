"""Durable Phase 36J course-package authority and learner progress."""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.auth import UserRecord
from app.db.models import (
    AcademyCourse,
    AcademyCoursePackage,
    AcademyEnrollment,
    AcademyLessonProgress,
    WorkforceMember,
    uuid_str,
)

PACKAGE_STATUSES = frozenset(
    {"queued", "building", "review_pending", "approved", "rejected", "failed"}
)
PROGRESS_STATUSES = frozenset({"not_started", "in_progress", "completed"})
SUPPORTED_LOCALES = ("ar", "en", "fr", "de", "es", "tr")


def now() -> datetime:
    return datetime.now(UTC)


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def package_snapshot(item: AcademyCoursePackage) -> dict[str, Any]:
    return {
        "id": item.id,
        "course_id": item.course_id,
        "status": item.status,
        "version": item.version,
        "lesson_count": item.lesson_count,
        "request": item.request_payload,
        "curriculum": item.curriculum,
        "citations": item.citations,
        "review": item.review,
        "archive_sha256": item.archive_sha256,
        "manifest_sha256": item.manifest_sha256,
        "archive_bytes": item.archive_bytes,
        "download_ready": bool(
            item.archive_relpath and item.status in {"review_pending", "approved"}
        ),
        "site_ready": bool(
            item.site_relpath and item.status in {"review_pending", "approved"}
        ),
        "error_code": item.error_code,
        "completed_at": iso(item.completed_at),
        "reviewed_at": iso(item.reviewed_at),
        "created_at": iso(item.created_at),
        "updated_at": iso(item.updated_at),
    }


def progress_snapshot(item: AcademyLessonProgress) -> dict[str, Any]:
    return {
        "id": item.id,
        "enrollment_id": item.enrollment_id,
        "package_id": item.package_id,
        "lesson_key": item.lesson_key,
        "locale": item.locale,
        "status": item.status,
        "progress_percent": item.progress_percent,
        "score": item.score,
        "attempts": item.attempts,
        "position": item.position,
        "completed_at": iso(item.completed_at),
        "updated_at": iso(item.updated_at),
    }


async def create_package_job(
    session: AsyncSession,
    actor: UserRecord,
    course: AcademyCourse,
    *,
    idempotency_key: str,
    domain: str,
    audience: str,
    locales: list[str],
    module_count: int,
    lessons_per_module: int,
    citations: list[dict[str, Any]],
) -> AcademyCoursePackage:
    key = idempotency_key.strip()
    if not key or len(key) > 160:
        raise ValueError("Course package idempotency key is required")
    if course.organization_id != actor.organization_id:
        raise PermissionError("Course is outside the actor organization")
    if course.status != "active":
        raise ValueError("Course is not active")
    normalized_locales = list(
        dict.fromkeys(value.strip().lower() for value in locales if value.strip())
    )
    if not normalized_locales or any(
        value not in SUPPORTED_LOCALES for value in normalized_locales
    ):
        raise ValueError("Unsupported course locale")
    if (
        not 1 <= module_count <= 8
        or not 1 <= lessons_per_module <= 8
        or module_count * lessons_per_module > 32
    ):
        raise ValueError("Course module/lesson counts are outside the allowed range")
    existing = await session.scalar(
        select(AcademyCoursePackage).where(
            AcademyCoursePackage.organization_id == actor.organization_id,
            AcademyCoursePackage.idempotency_key == key,
        )
    )
    if existing is not None:
        return existing
    max_version = int(
        await session.scalar(
            select(func.max(AcademyCoursePackage.version)).where(
                AcademyCoursePackage.course_id == course.id
            )
        )
        or 0
    )
    item = AcademyCoursePackage(
        id=uuid_str(),
        organization_id=actor.organization_id,
        course_id=course.id,
        requested_by_id=actor.id,
        idempotency_key=key,
        status="queued",
        version=max_version + 1,
        lesson_count=module_count * lessons_per_module,
        request_payload={
            "domain": domain.strip(),
            "audience": audience.strip(),
            "locales": normalized_locales,
            "module_count": module_count,
            "lessons_per_module": lessons_per_module,
            "passing_score": course.passing_score,
            "citations": citations,
        },
        citations=citations,
        review={"status": "pending", "approved": False},
    )
    session.add(item)
    await session.flush()
    return item


async def claim_next_package(
    session: AsyncSession, *, stale_after_seconds: int = 1_800
) -> AcademyCoursePackage | None:
    if not 60 <= stale_after_seconds <= 86_400:
        raise ValueError(
            "Course package stale-build window is outside the allowed range"
        )
    cutoff = now() - timedelta(seconds=stale_after_seconds)
    stale = await session.scalar(
        select(AcademyCoursePackage)
        .where(
            AcademyCoursePackage.status == "building",
            AcademyCoursePackage.updated_at < cutoff,
        )
        .order_by(AcademyCoursePackage.updated_at, AcademyCoursePackage.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if stale is not None:
        stale.status = "queued"
        stale.error_code = "stale_build_recovered"
        stale.error_message = (
            "A stale course build was recovered after the bounded lease window."
        )
        await session.flush()

    item = await session.scalar(
        select(AcademyCoursePackage)
        .where(AcademyCoursePackage.status == "queued")
        .order_by(AcademyCoursePackage.created_at, AcademyCoursePackage.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if item is None:
        return None
    item.status = "building"
    item.error_code = None
    item.error_message = None
    await session.flush()
    return item


async def complete_package(
    session: AsyncSession,
    item: AcademyCoursePackage,
    *,
    site_relpath: str,
    archive_relpath: str,
    archive_sha256: str,
    manifest_sha256: str,
    archive_bytes: int,
    curriculum: dict[str, Any],
) -> None:
    for digest in (archive_sha256, manifest_sha256):
        if len(digest) != 64 or any(
            c not in "0123456789abcdef" for c in digest.lower()
        ):
            raise ValueError("Invalid course package digest")
    item.site_relpath = site_relpath
    item.archive_relpath = archive_relpath
    item.archive_sha256 = archive_sha256
    item.manifest_sha256 = manifest_sha256
    item.archive_bytes = archive_bytes
    item.curriculum = curriculum
    item.status = "review_pending"
    item.completed_at = now()
    item.review = {
        "status": "pending",
        "approved": False,
        "checks": [
            "curriculum",
            "citations",
            "answer-key",
            "localization",
            "media-assets",
            "accessibility",
        ],
    }
    await session.flush()


async def fail_package(
    session: AsyncSession, item: AcademyCoursePackage, *, code: str, message: str
) -> None:
    item.status = "failed"
    item.error_code = code[:120]
    item.error_message = message[:2000]
    await session.flush()


async def review_package(
    session: AsyncSession,
    actor: UserRecord,
    item: AcademyCoursePackage,
    *,
    approved: bool,
    notes: str,
) -> AcademyCoursePackage:
    if item.organization_id != actor.organization_id:
        raise PermissionError("Package is outside the actor organization")
    if item.status not in {"review_pending", "approved", "rejected"}:
        raise ValueError("Course package is not reviewable")
    item.status = "approved" if approved else "rejected"
    item.reviewed_by_id = actor.id
    item.reviewed_at = now()
    item.review = {
        "status": "approved" if approved else "rejected",
        "approved": approved,
        "reviewer_id": actor.id,
        "notes": notes.strip() or None,
        "reviewed_at": iso(item.reviewed_at),
    }
    await session.flush()
    return item


async def update_progress(
    session: AsyncSession,
    actor: UserRecord,
    *,
    enrollment: AcademyEnrollment,
    package: AcademyCoursePackage,
    lesson_key: str,
    locale: str,
    progress_percent: float,
    score: float | None,
    position: dict[str, Any],
) -> AcademyLessonProgress:
    if (
        enrollment.organization_id != actor.organization_id
        or package.organization_id != actor.organization_id
        or enrollment.course_id != package.course_id
    ):
        raise PermissionError("Academy progress scope mismatch")
    member = await session.get(WorkforceMember, enrollment.worker_id)
    granted = set(actor.permissions)
    if member is None or (
        member.user_id != actor.id
        and "*" not in granted
        and "academy:assess" not in granted
    ):
        raise PermissionError("Learner progress is not writable by this actor")
    if package.status != "approved":
        raise ValueError("Learner progress requires an approved course package")
    if locale not in (package.request_payload or {}).get("locales", []):
        raise ValueError("Progress locale is outside the package")
    valid_keys = {
        str(row.get("key"))
        for row in (package.curriculum or {}).get("lessons", [])
        if isinstance(row, dict)
    }
    if lesson_key not in valid_keys:
        raise ValueError("Unknown course lesson")
    if not 0 <= progress_percent <= 100 or score is not None and not 0 <= score <= 100:
        raise ValueError("Progress score is outside the allowed range")
    item = await session.scalar(
        select(AcademyLessonProgress)
        .where(
            AcademyLessonProgress.enrollment_id == enrollment.id,
            AcademyLessonProgress.package_id == package.id,
            AcademyLessonProgress.lesson_key == lesson_key,
        )
        .with_for_update()
    )
    if item is None:
        item = AcademyLessonProgress(
            id=uuid_str(),
            organization_id=actor.organization_id,
            enrollment_id=enrollment.id,
            package_id=package.id,
            lesson_key=lesson_key,
            locale=locale,
        )
        session.add(item)
    item.locale = locale
    item.progress_percent = progress_percent
    item.score = score
    item.attempts = int(item.attempts or 0) + (1 if score is not None else 0)
    item.position = position
    if progress_percent >= 100:
        item.status = "completed"
        item.completed_at = item.completed_at or now()
    elif progress_percent > 0:
        item.status = "in_progress"
    else:
        item.status = "not_started"
    await session.flush()
    return item


async def analytics_snapshot(
    session: AsyncSession, *, organization_id: str, course_id: str
) -> dict[str, Any]:
    package_count = int(
        await session.scalar(
            select(func.count(AcademyCoursePackage.id)).where(
                AcademyCoursePackage.organization_id == organization_id,
                AcademyCoursePackage.course_id == course_id,
            )
        )
        or 0
    )
    enrollment_count = int(
        await session.scalar(
            select(func.count(AcademyEnrollment.id)).where(
                AcademyEnrollment.organization_id == organization_id,
                AcademyEnrollment.course_id == course_id,
            )
        )
        or 0
    )
    progress_rows = list(
        (
            await session.scalars(
                select(AcademyLessonProgress)
                .join(
                    AcademyCoursePackage,
                    AcademyLessonProgress.package_id == AcademyCoursePackage.id,
                )
                .where(
                    AcademyLessonProgress.organization_id == organization_id,
                    AcademyCoursePackage.course_id == course_id,
                )
            )
        ).all()
    )
    completed = sum(1 for row in progress_rows if row.status == "completed")
    scores = [float(row.score) for row in progress_rows if row.score is not None]
    return {
        "course_id": course_id,
        "package_count": package_count,
        "enrollment_count": enrollment_count,
        "lesson_progress_records": len(progress_rows),
        "completed_lessons": completed,
        "average_score": round(sum(scores) / len(scores), 2) if scores else None,
    }


def resolve_package_path(root: Path, relpath: str | None) -> Path:
    if not relpath:
        raise FileNotFoundError("Course package artifact is unavailable")
    rel = PurePosixPath(relpath)
    if rel.is_absolute() or ".." in rel.parts:
        raise FileNotFoundError("Course package path is invalid")
    base = root.resolve()
    path = (base / Path(*rel.parts)).resolve()
    try:
        path.relative_to(base)
    except ValueError as exc:
        raise FileNotFoundError("Course package path escaped storage") from exc
    if not path.is_file():
        raise FileNotFoundError("Course package artifact is missing")
    return path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()
