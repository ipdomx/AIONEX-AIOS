"""Phase 36J local course-package worker using the governed FFmpeg 9 image."""
from __future__ import annotations
import argparse
import asyncio
import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from aios.course_factory import (
    CourseCitation,
    CourseFactoryRequest,
    CompleteCourseFactory,
    LocalFFmpegCourseVideoRenderer,
)
from app.db.base import SessionLocal
from app.db.models import AcademyCourse, AcademyCoursePackage
from app.services import academy_course_runtime as runtime

ROOT = Path(os.getenv("ACADEMY_COURSE_PACKAGE_ROOT", "/var/lib/aionex/course-packages"))
HEALTH = ROOT / ".worker-health.json"


def _write_health(*, status: str, cycles: int, errors: int) -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    temp = HEALTH.with_suffix(f".tmp-{os.getpid()}")
    temp.write_text(
        json.dumps(
            {
                "status": status,
                "cycles": cycles,
                "errors": errors,
                "updated_at": datetime.now(UTC).isoformat(),
                "enabled": os.getenv("ACADEMY_COURSE_WORKER_ENABLED", "false").lower()
                == "true",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    os.chmod(temp, 0o600)
    os.replace(temp, HEALTH)


async def run_once() -> bool:
    async with SessionLocal() as session:
        async with session.begin():
            item = await runtime.claim_next_package(session)
        if item is None:
            return False
        item_id = item.id
    async with SessionLocal() as session:
        item = await session.get(AcademyCoursePackage, item_id)
        if item is None:
            return False
        course = await session.get(AcademyCourse, item.course_id)
        if course is None:
            await runtime.fail_package(
                session,
                item,
                code="course_missing",
                message="Academy course is unavailable",
            )
            await session.commit()
            return True
        payload = dict(item.request_payload or {})
        citations = tuple(
            CourseCitation(
                str(c.get("citation_id") or f"source-{i+1}"),
                str(c.get("title") or "Course source"),
                str(c.get("uri") or "internal://aionex/course"),
                str(c.get("author")) if c.get("author") else None,
            )
            for i, c in enumerate(payload.get("citations") or [])
        )
        request = CourseFactoryRequest(
            course_id=f"{course.code.lower()}-v{item.version}",
            title=course.title,
            domain=str(payload.get("domain") or course.title),
            audience=str(payload.get("audience") or "learners"),
            locales=tuple(payload.get("locales") or ["en"]),
            module_count=int(payload.get("module_count") or 2),
            lessons_per_module=int(payload.get("lessons_per_module") or 2),
            passing_score=float(payload.get("passing_score") or course.passing_score),
            citations=citations,
        )
        work = ROOT / ".tmp" / item.id
        final_dir = ROOT / item.organization_id / item.course_id / f"v{item.version}"
        archive_target = (
            ROOT / item.organization_id / item.course_id / f"course-v{item.version}.zip"
        )
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True, exist_ok=True)
        try:
            result = CompleteCourseFactory(LocalFFmpegCourseVideoRenderer()).build(
                request, work / "site"
            )
            curriculum = json.loads(
                (work / "site" / "curriculum.json").read_text(encoding="utf-8")
            )
            final_dir.parent.mkdir(parents=True, exist_ok=True)
            archive_target.parent.mkdir(parents=True, exist_ok=True)
            if final_dir.exists():
                shutil.rmtree(final_dir)
            os.replace(work / "site", final_dir)
            os.replace(result.archive_path, archive_target)
            await runtime.complete_package(
                session,
                item,
                site_relpath=final_dir.relative_to(ROOT).as_posix(),
                archive_relpath=archive_target.relative_to(ROOT).as_posix(),
                archive_sha256=result.archive_sha256,
                manifest_sha256=result.manifest_sha256,
                archive_bytes=archive_target.stat().st_size,
                curriculum=curriculum,
            )
        except Exception as exc:
            await runtime.fail_package(
                session, item, code="course_build_failed", message=type(exc).__name__
            )
        finally:
            shutil.rmtree(work, ignore_errors=True)
        await session.commit()
        return True


async def loop() -> None:
    cycles = errors = 0
    _write_health(status="starting", cycles=0, errors=0)
    while True:
        try:
            worked = await run_once()
            cycles += 1
            _write_health(status="healthy", cycles=cycles, errors=errors)
            if not worked:
                await asyncio.sleep(2)
        except Exception:
            errors += 1
            _write_health(status="degraded", cycles=cycles, errors=errors)
            await asyncio.sleep(2)


def healthcheck() -> int:
    try:
        data = json.loads(HEALTH.read_text(encoding="utf-8"))
        updated = datetime.fromisoformat(data["updated_at"])
        age = (datetime.now(UTC) - updated).total_seconds()
        return 0 if data.get("status") in {"healthy", "starting"} and age < 120 else 1
    except Exception:
        return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--healthcheck", action="store_true")
    args = parser.parse_args()
    if args.healthcheck:
        return healthcheck()
    if os.getenv("ACADEMY_COURSE_WORKER_ENABLED", "false").lower() != "true":
        _write_health(status="disabled", cycles=0, errors=0)
        return 0
    if args.once:
        return 0 if asyncio.run(run_once()) else 0
    asyncio.run(loop())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
