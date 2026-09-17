"""Local Academy builds with durable activity ownership and settled file I/O."""
from __future__ import annotations

import argparse
import asyncio
import ctypes
import errno
import json
import logging
import os
import platform
import stat
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar
from uuid import uuid4

from aios.course_factory import (
    CompleteCourseFactory,
    CourseCitation,
    CourseFactoryRequest,
    CoursePackageResult,
    LocalFFmpegCourseVideoRenderer,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.base import SessionLocal
from app.db.models import AcademyCourse, AcademyCoursePackage
from app.services import academy_course_runtime as runtime
from app.services import host_maintenance_academy as maintenance

ROOT = Path(os.getenv("ACADEMY_COURSE_PACKAGE_ROOT", "/var/lib/aionex/course-packages"))
HEALTH = ROOT / ".worker-health.json"
WORKER_INCARNATION = str(uuid4())
HEARTBEAT_INTERVAL_SECONDS = 20.0
logger = logging.getLogger(__name__)

SessionFactory = async_sessionmaker[AsyncSession]
BuildCallable = Callable[[CourseFactoryRequest, Path], CoursePackageResult]
T = TypeVar("T")


@dataclass(frozen=True)
class PackageBuildInput:
    root: Path
    activity_id: str
    package_id: str
    organization_id: str
    course_id: str
    version: int
    request: CourseFactoryRequest


@dataclass(frozen=True)
class PackageIOOutcome:
    site_relpath: str | None = None
    archive_relpath: str | None = None
    archive_sha256: str | None = None
    manifest_sha256: str | None = None
    archive_bytes: int = 0
    curriculum: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    unresolved_reason: str | None = None


class AcademyWorkUnresolved(RuntimeError):
    """Work or publication requires reconciliation before its owner can finish."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class _ExistingPublication(RuntimeError):
    pass


class _BuildInterrupted(RuntimeError):
    pass


def _write_health(
    *, status: str, cycles: int, errors: int, root: Path | None = None
) -> None:
    # This liveness write is control-plane work, explicitly outside the partial
    # Academy package activity snapshot. It continues while admission is closed.
    base = ROOT if root is None else root
    health = HEALTH if root is None else base / ".worker-health.json"
    base.mkdir(parents=True, exist_ok=True)
    temp = health.with_suffix(f".tmp-{os.getpid()}")
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
    os.replace(temp, health)


def _default_builder(request: CourseFactoryRequest, destination: Path) -> CoursePackageResult:
    return CompleteCourseFactory(LocalFFmpegCourseVideoRenderer()).build(
        request, destination
    )


def _component(value: str) -> str:
    if not value or value in {".", ".."} or "/" in value or "\\" in value:
        raise ValueError("Invalid Academy artifact identifier")
    return value


def _check_stop(stop_event: threading.Event) -> None:
    if stop_event.is_set():
        raise _BuildInterrupted("Academy build was interrupted")


def _destination_absent(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return True
    return False



def _publish_noreplace(source: Path, destination: Path) -> None:
    """Atomically publish on Linux without replacing any existing destination.

    Alpine musl need not export renameat2. The direct syscall fallback is limited
    to the verified Linux x86_64 64-bit ABI; unsupported systems fail closed.
    Neither branch falls back to an operation that can replace a destination.
    """
    if sys.platform != "linux":
        raise OSError("Atomic Academy publication requires Linux")
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        rename = getattr(libc, "renameat2", None)
        if rename is not None:
            rename.argtypes = (
                ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                ctypes.c_char_p, ctypes.c_uint,
            )
            rename.restype = ctypes.c_int
            result = rename(-100, os.fsencode(source), -100, os.fsencode(destination), 1)
        else:
            if (
                platform.machine().lower() not in {"x86_64", "amd64"}
                or ctypes.sizeof(ctypes.c_void_p) != 8
                or ctypes.sizeof(ctypes.c_long) != 8
            ):
                raise OSError("Atomic Academy publication ABI is unsupported")
            syscall = libc.syscall
            syscall.restype = ctypes.c_long
            # Linux UAPI: asm/unistd_64.h __NR_renameat2=316;
            # linux/fcntl.h AT_FDCWD=-100; linux/fs.h RENAME_NOREPLACE=1.
            result = syscall(
                ctypes.c_long(316),
                ctypes.c_int(-100), ctypes.c_char_p(os.fsencode(source)),
                ctypes.c_int(-100), ctypes.c_char_p(os.fsencode(destination)),
                ctypes.c_uint(1),
            )
    except (AttributeError, OSError):
        raise OSError("Atomic Academy publication is unavailable") from None
    if result != 0:
        error = ctypes.get_errno()
        if error in {errno.EEXIST, errno.ENOTEMPTY}:
            raise _ExistingPublication("Academy publication already exists")
        raise OSError(error, "Atomic Academy publication failed")


def _same_inode(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _remove_directory_contents(directory_fd: int) -> None:
    """Traverse only pinned directory identities, never a reopened root path."""
    for name in os.listdir(directory_fd):
        observed = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        is_directory = stat.S_ISDIR(observed.st_mode)
        flags = os.O_DIRECTORY | os.O_RDONLY if is_directory else os.O_PATH
        entry_fd = os.open(
            name, flags | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory_fd
        )
        try:
            pinned = os.fstat(entry_fd)
            if not _same_inode(observed, pinned):
                raise OSError("Academy staging entry identity changed")
            if is_directory:
                _remove_directory_contents(entry_fd)
            current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if not _same_inode(pinned, current):
                raise OSError("Academy staging entry binding changed")
            if is_directory:
                os.rmdir(name, dir_fd=directory_fd)
                if os.fstat(entry_fd).st_nlink != 0:
                    raise OSError("Academy staging directory removal is uncertain")
            else:
                os.unlink(name, dir_fd=directory_fd)
                if os.fstat(entry_fd).st_nlink != pinned.st_nlink - 1:
                    raise OSError("Academy staging entry removal is uncertain")
        finally:
            os.close(entry_fd)


def _cleanup_owned_stage(
    stage: Path,
    parent_fd: int,
    stage_fd: int,
    identity: tuple[int, int],
) -> None:
    """Remove this attempt's pinned stage and reject namespace substitution.

    Recursive deletion never reopens stage by pathname. Final entry removal is
    still a name operation, not inode-CAS: a last-instant empty-directory swap
    may remove that empty entry. The original fd link count must then prove its
    own removal or the activity stays unresolved. A replacement tree's contents
    are never adopted through a recursive pathname lookup.
    """
    def verify_binding() -> None:
        pinned = os.fstat(stage_fd)
        parent = os.fstat(parent_fd)
        if (
            not stat.S_ISDIR(pinned.st_mode)
            or (pinned.st_dev, pinned.st_ino) != identity
            or not _same_inode(parent, stage.parent.stat(follow_symlinks=False))
        ):
            raise OSError("Academy staging ownership changed")
        current = os.stat(stage.name, dir_fd=parent_fd, follow_symlinks=False)
        if not _same_inode(pinned, current) or not stat.S_ISDIR(current.st_mode):
            raise OSError("Academy staging pathname changed")

    verify_binding()
    _remove_directory_contents(stage_fd)
    verify_binding()
    os.rmdir(stage.name, dir_fd=parent_fd)
    if os.fstat(stage_fd).st_nlink != 0:
        raise OSError("Academy staging root removal is uncertain")


def _build_publish_cleanup(
    build: PackageBuildInput,
    stop_event: threading.Event,
    *,
    builder: BuildCallable,
) -> PackageIOOutcome:
    """Own all staging I/O until strict cleanup has really returned.

    The synchronous factory is unchanged. Cancellation can ask this helper to
    stop between phases; it cannot stop a factory/FFmpeg call already underway.
    Its caller must retain and join the actual thread task.
    """
    stage: Path | None = None
    stage_identity: tuple[int, int] | None = None
    parent_fd: int | None = None
    stage_fd: int | None = None
    publication_started = False
    outcome = PackageIOOutcome()
    interruption: BaseException | None = None
    try:
        _check_stop(stop_event)
        root = build.root.resolve()
        organization_id = _component(build.organization_id)
        course_id = _component(build.course_id)
        activity_id = _component(build.activity_id)
        _component(build.package_id)
        if build.version < 1:
            raise ValueError("Invalid Academy package version")
        final_dir = root / organization_id / course_id / f"v{build.version}"
        archive_target = root / organization_id / course_id / f"course-v{build.version}.zip"
        for target in (final_dir, archive_target):
            if not _destination_absent(target):
                raise _ExistingPublication("Academy publication already exists")
        # Validate existing parents before creating this attempt's private stage.
        for directory in (root / ".tmp", root / organization_id, final_dir.parent):
            if directory.is_symlink():
                raise _ExistingPublication("Academy artifact parent is not a directory")
        stage = root / ".tmp" / activity_id
        stage.parent.mkdir(parents=True, exist_ok=True)
        directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        parent_fd = os.open(stage.parent, directory_flags)
        os.mkdir(stage.name, mode=0o700, dir_fd=parent_fd)
        metadata = os.stat(stage.name, dir_fd=parent_fd, follow_symlinks=False)
        stage_identity = (metadata.st_dev, metadata.st_ino)
        stage_fd = os.open(stage.name, directory_flags, dir_fd=parent_fd)
        if not _same_inode(metadata, os.fstat(stage_fd)):
            raise _ExistingPublication("Academy staging ownership changed")
        _check_stop(stop_event)
        result = builder(build.request, stage / "site")
        _check_stop(stop_event)
        site = stage / "site"
        if site.is_symlink() or not site.is_dir():
            raise ValueError("Academy factory site is unavailable")
        archive = result.archive_path.resolve()
        if not archive.is_relative_to(stage.resolve()) or not archive.is_file():
            raise ValueError("Academy factory archive escaped its staging directory")
        curriculum = json.loads((site / "curriculum.json").read_text(encoding="utf-8"))
        if not isinstance(curriculum, dict):
            raise ValueError("Academy curriculum must be an object")
        final_dir.parent.mkdir(parents=True, exist_ok=True)
        # There is only one admitted owner for this package/version. Existing
        # destinations are provenance requiring reconciliation, never overwrite.
        for target in (final_dir, archive_target):
            if not _destination_absent(target):
                raise _ExistingPublication("Academy publication appeared during build")
        _check_stop(stop_event)
        publication_started = True
        _publish_noreplace(site, final_dir)
        _check_stop(stop_event)
        _publish_noreplace(archive, archive_target)
        _check_stop(stop_event)
        outcome = PackageIOOutcome(
            site_relpath=final_dir.relative_to(root).as_posix(),
            archive_relpath=archive_target.relative_to(root).as_posix(),
            archive_sha256=result.archive_sha256,
            manifest_sha256=result.manifest_sha256,
            archive_bytes=archive_target.stat().st_size,
            curriculum=curriculum,
        )
    except BaseException as exc:
        reason = None
        if isinstance(exc, _BuildInterrupted):
            reason = "academy-build-interrupted"
        elif isinstance(exc, _ExistingPublication):
            reason = "academy-existing-publication"
        elif publication_started:
            reason = "academy-publication-incomplete"
        elif stage is not None and (stage_identity is None or stage_fd is None):
            # mkdir/lstat failure cannot establish exclusive staging ownership.
            reason = "academy-staging-unverified"
        elif not isinstance(exc, Exception):
            reason = "academy-build-interrupted"
        outcome = PackageIOOutcome(
            error_code="course_build_failed",
            error_message=type(exc).__name__,
            unresolved_reason=reason,
        )
        if not isinstance(exc, Exception):
            interruption = exc
    finally:
        if (
            stage is not None
            and stage_identity is not None
            and parent_fd is not None
            and stage_fd is not None
        ):
            try:
                # Includes the archive beside site, anchored to our original fd.
                _cleanup_owned_stage(stage, parent_fd, stage_fd, stage_identity)
            except BaseException as exc:
                outcome = PackageIOOutcome(
                    error_code="course_build_failed",
                    error_message="AcademyCleanupIncomplete",
                    unresolved_reason="academy-cleanup-incomplete",
                )
                if not isinstance(exc, Exception) and interruption is None:
                    interruption = exc
        for descriptor in (stage_fd, parent_fd):
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    outcome = PackageIOOutcome(
                        error_code="course_build_failed",
                        error_message="AcademyCleanupIncomplete",
                        unresolved_reason="academy-cleanup-incomplete",
                    )
    if interruption is not None:
        raise interruption
    return outcome


async def _settled_task_result(task: asyncio.Task[T]) -> T:
    """Join a retained task despite repeated cancellation of its waiter."""
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
        except BaseException:
            break
    return task.result()


async def _load_build_input(
    ownership: maintenance.AcademyActivityOwnership,
    *,
    root: Path,
    session_factory: SessionFactory,
) -> PackageBuildInput | None:
    async with session_factory() as session:
        async with session.begin():
            await maintenance.require_owned_academy_activity(session, ownership)
            item = await session.get(AcademyCoursePackage, ownership.package_id)
            if item is None:
                raise maintenance.AcademyActivityOwnershipLost("Academy package is unavailable")
            course = await session.get(AcademyCourse, item.course_id)
            if course is None:
                return None
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
            return PackageBuildInput(
                root=root,
                activity_id=ownership.activity_id,
                package_id=item.id,
                organization_id=item.organization_id,
                course_id=item.course_id,
                version=item.version,
                request=request,
            )


async def _commit_outcome(
    ownership: maintenance.AcademyActivityOwnership,
    outcome: PackageIOOutcome,
    *,
    session_factory: SessionFactory,
) -> None:
    async with session_factory() as session:
        async with session.begin():
            item = await session.get(AcademyCoursePackage, ownership.package_id)
            if item is None:
                raise maintenance.AcademyActivityOwnershipLost("Academy package is unavailable")
            if outcome.error_code is not None:
                await runtime.fail_package(
                    session,
                    item,
                    ownership=ownership,
                    code=outcome.error_code,
                    message=outcome.error_message or "Course build failed",
                )
            else:
                if (
                    outcome.site_relpath is None
                    or outcome.archive_relpath is None
                    or outcome.archive_sha256 is None
                    or outcome.manifest_sha256 is None
                    or outcome.curriculum is None
                ):
                    raise AcademyWorkUnresolved("academy-result-incomplete")
                await runtime.complete_package(
                    session,
                    item,
                    ownership=ownership,
                    site_relpath=outcome.site_relpath,
                    archive_relpath=outcome.archive_relpath,
                    archive_sha256=outcome.archive_sha256,
                    manifest_sha256=outcome.manifest_sha256,
                    archive_bytes=outcome.archive_bytes,
                    curriculum=outcome.curriculum,
                )
        # Return only after the terminal business transaction committed.


async def _execute_owned_package(
    ownership: maintenance.AcademyActivityOwnership,
    stop_event: threading.Event,
    *,
    root: Path,
    builder: BuildCallable,
    session_factory: SessionFactory,
) -> None:
    try:
        build = await _load_build_input(
            ownership, root=root, session_factory=session_factory
        )
    except (ValueError, TypeError, KeyError) as exc:
        await _commit_outcome(
            ownership,
            PackageIOOutcome(error_code="course_build_failed", error_message=type(exc).__name__),
            session_factory=session_factory,
        )
        return
    if build is None:
        await _commit_outcome(
            ownership,
            PackageIOOutcome(error_code="course_missing", error_message="Academy course is unavailable"),
            session_factory=session_factory,
        )
        return
    _check_stop(stop_event)
    io_task = asyncio.create_task(
        asyncio.to_thread(_build_publish_cleanup, build, stop_event, builder=builder)
    )
    try:
        outcome = await asyncio.shield(io_task)
    except BaseException:
        stop_event.set()
        try:
            await _settled_task_result(io_task)
        except BaseException:
            # The original interruption remains primary. Its durable owner is
            # retained by run_once, irrespective of the eventual thread result.
            pass
        raise
    if outcome.unresolved_reason is not None:
        raise AcademyWorkUnresolved(outcome.unresolved_reason)
    _check_stop(stop_event)
    await _commit_outcome(ownership, outcome, session_factory=session_factory)


async def _heartbeat_activity(
    ownership: maintenance.AcademyActivityOwnership,
    stop: asyncio.Event,
    *,
    root: Path,
    interval: float,
    session_factory: SessionFactory,
) -> None:
    while not stop.is_set():
        await maintenance.heartbeat_academy_activity(
            ownership, phase="build-or-finalize", session_factory=session_factory
        )
        _write_health(status="healthy", cycles=0, errors=0, root=root)
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except TimeoutError:
            pass


async def _retain_uncertainty(
    ownership: maintenance.AcademyActivityOwnership,
    *,
    reason: str,
    session_factory: SessionFactory,
) -> None:
    async def record() -> None:
        try:
            await maintenance.mark_academy_activity_unresolved(
                ownership, reason=reason, session_factory=session_factory
            )
        except BaseException:
            # A failed update does not authorize finish: the durable row, or a
            # building package with missing ownership, remains a drain blocker.
            logger.warning("Academy activity uncertainty could not be recorded")

    await _settled_task_result(asyncio.create_task(record()))


async def run_once(
    *,
    session_factory: SessionFactory | None = None,
    root: Path | None = None,
    worker_incarnation: str | None = None,
    builder: BuildCallable | None = None,
    heartbeat_interval_seconds: float = HEARTBEAT_INTERVAL_SECONDS,
) -> bool:
    factory = SessionLocal if session_factory is None else session_factory
    base = ROOT if root is None else root
    incarnation = WORKER_INCARNATION if worker_incarnation is None else worker_incarnation
    build_function = _default_builder if builder is None else builder
    if not 0 < heartbeat_interval_seconds < maintenance.ACTIVITY_LEASE_SECONDS / 2:
        raise ValueError("Academy heartbeat interval is outside the allowed range")
    ownership: maintenance.AcademyActivityOwnership | None = None
    try:
        async with factory() as session:
            async with session.begin():
                ownership = await runtime.claim_next_package(
                    session, worker_incarnation=incarnation
                )
            # Neither a thread nor package I/O begins before claim/owner commit.
    except BaseException:
        if ownership is not None:
            # A rejected/ambiguous COMMIT never starts I/O. If the database did
            # commit ownership despite a lost reply, retain it for reconciliation.
            await _retain_uncertainty(
                ownership,
                reason="academy-claim-commit-uncertain",
                session_factory=factory,
            )
        raise
    if ownership is None:
        return False
    thread_stop = threading.Event()
    heartbeat_stop = asyncio.Event()
    operation = asyncio.create_task(
        _execute_owned_package(
            ownership,
            thread_stop,
            root=base,
            builder=build_function,
            session_factory=factory,
        )
    )
    heartbeat = asyncio.create_task(
        _heartbeat_activity(
            ownership,
            heartbeat_stop,
            root=base,
            interval=heartbeat_interval_seconds,
            session_factory=factory,
        )
    )
    try:
        done, _ = await asyncio.wait(
            {operation, heartbeat}, return_when=asyncio.FIRST_COMPLETED
        )
        if operation in done:
            operation.result()
            heartbeat_stop.set()
            # The registry heartbeat permits terminal package status while
            # finish is pending, so joining it has no terminal-status lease race.
            await heartbeat
        else:
            heartbeat.result()
            raise AcademyWorkUnresolved("academy-heartbeat-stopped")
        await maintenance.finish_academy_activity(ownership, session_factory=factory)
        return True
    except BaseException as exc:
        thread_stop.set()
        heartbeat_stop.set()
        reason = (
            exc.reason
            if isinstance(exc, AcademyWorkUnresolved)
            else "academy-interrupted"
            if isinstance(exc, asyncio.CancelledError)
            else "academy-worker-uncertain"
        )
        # Persist uncertainty before waiting for potentially lengthy thread I/O.
        await _retain_uncertainty(ownership, reason=reason, session_factory=factory)
        if not operation.done():
            operation.cancel()
        if not heartbeat.done():
            heartbeat.cancel()
        for task in (operation, heartbeat):
            try:
                await _settled_task_result(task)
            except BaseException:
                pass
        raise


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
