"""Bounded, disk-backed downloadable project archive for authenticated executions.

The caller must first enforce tenant/project/execution membership and completion.
This module never opens network sockets, runs generated code or trusts file names
supplied by model output. It only packages retained local delivery evidence.
"""
from __future__ import annotations

import hashlib
import os
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

# A 3D application's real browser bundle and images can exceed the legacy 50 MiB
# cap. This upper bound keeps the disk and per-request CPU budgets finite.
MAX_DELIVERY_FILES = 1000
MAX_DELIVERY_SOURCE_BYTES = 256 * 1024 * 1024
MAX_APPROVAL_RECEIPT_BYTES = 64 * 1024
ARCHIVE_CHUNK_BYTES = 1024 * 1024


class ProjectDeliveryArchiveError(ValueError):
    """Cannot safely archive this retained project deliverable."""

    def __init__(self, message: str, *, status_code: int = 409) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class ProjectDeliveryArchive:
    """Private auto-unlinked ZIP: the caller must close the stream."""

    stream: BinaryIO
    length: int
    sha256: str


def _safe_regular_file(path: Path, root: Path) -> tuple[Path, int]:
    """Validate a regular non-symlink file and an unchanged containing root."""
    if path.is_symlink():
        raise ProjectDeliveryArchiveError("Project delivery contains an unsafe link")
    try:
        info = path.lstat()
        actual = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ProjectDeliveryArchiveError("Project delivery file is unavailable") from exc
    if not stat.S_ISREG(info.st_mode) or root not in actual.parents:
        raise ProjectDeliveryArchiveError("Project delivery file escapes its package")
    # A hardlink can have an innocuous path inside the package but reference a
    # sensitive file outside. Reviewed deliverables must be ordinary single-link files.
    if info.st_nlink != 1:
        raise ProjectDeliveryArchiveError("Project delivery contains an unsafe hardlink")
    return actual, info.st_size


def _inventory(package_root: Path, evidence_root: Path) -> list[tuple[Path, str, int]]:
    if package_root.is_symlink() or evidence_root.is_symlink():
        raise ProjectDeliveryArchiveError("Project delivery root is unsafe")
    try:
        root = package_root.resolve(strict=True)
        parent = evidence_root.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ProjectDeliveryArchiveError("Project delivery root is unavailable") from exc
    if parent not in root.parents or not root.is_dir():
        raise ProjectDeliveryArchiveError("Project delivery root is unsafe")

    items: list[tuple[Path, str, int]] = []
    total_bytes = 0
    for candidate in root.rglob("*"):
        if candidate.is_symlink():
            raise ProjectDeliveryArchiveError("Project delivery contains an unsafe link")
        if candidate.is_dir():
            # A changed nested directory or an escaped path is not part of a
            # legitimate reviewed artifact tree.
            if root not in candidate.resolve(strict=True).parents:
                raise ProjectDeliveryArchiveError("Project delivery path escaped its root")
            continue
        path, length = _safe_regular_file(candidate, root)
        relative = candidate.relative_to(root).as_posix()
        if not relative or relative.startswith("/") or ".." in Path(relative).parts:
            raise ProjectDeliveryArchiveError("Project delivery filename is invalid")
        if relative == "owner-approval.json":
            # This reserved entry is only ever drawn from the protected
            # evidence root, never from arbitrary generated delivery content.
            raise ProjectDeliveryArchiveError("Project delivery contains a reserved receipt name")
        items.append((path, relative, length))
        total_bytes += length
        if len(items) > MAX_DELIVERY_FILES:
            raise ProjectDeliveryArchiveError("Project delivery contains too many files")
        if total_bytes > MAX_DELIVERY_SOURCE_BYTES:
            raise ProjectDeliveryArchiveError("Project delivery package is too large", status_code=413)
    if not items:
        raise ProjectDeliveryArchiveError("Project delivery package is empty")

    approval = parent / "owner-approval.json"
    if approval.exists() or approval.is_symlink():
        path, length = _safe_regular_file(approval, parent)
        if length > MAX_APPROVAL_RECEIPT_BYTES:
            raise ProjectDeliveryArchiveError("Owner approval receipt is invalid")
        if len(items) >= MAX_DELIVERY_FILES:
            raise ProjectDeliveryArchiveError("Project delivery contains too many files")
        items.append((path, "owner-approval.json", length))
    return sorted(items, key=lambda item: item[1])


def _append_verified_file(bundle: zipfile.ZipFile, file: Path, name: str, allowed: int) -> None:
    """Read by O_NOFOLLOW descriptor, not a potentially replaced pathname."""
    try:
        before = file.lstat()
        fd = os.open(file, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise ProjectDeliveryArchiveError("Project delivery file changed during packaging") from exc
    with os.fdopen(fd, "rb") as inp:
        current = os.fstat(inp.fileno())
        if (
            not stat.S_ISREG(current.st_mode)
            or current.st_dev != before.st_dev
            or current.st_ino != before.st_ino
            or current.st_size != allowed
        ):
            raise ProjectDeliveryArchiveError("Project delivery file changed during packaging")
        entry = zipfile.ZipInfo(name)
        entry.compress_type = zipfile.ZIP_DEFLATED
        entry.external_attr = (stat.S_IFREG | 0o600) << 16
        count = 0
        with bundle.open(entry, "w", force_zip64=True) as out:
            while chunk := inp.read(ARCHIVE_CHUNK_BYTES):
                count += len(chunk)
                if count > allowed:
                    raise ProjectDeliveryArchiveError("Project delivery file grew during packaging")
                out.write(chunk)
        if count != allowed or os.fstat(inp.fileno()).st_size != allowed:
            raise ProjectDeliveryArchiveError("Project delivery file changed during packaging")


def build_project_delivery_archive(
    package_root: Path, evidence_root: Path
) -> ProjectDeliveryArchive:
    """Build a bounded ZIP on private temporary disk, never in a BytesIO buffer.

    A tempfile.TemporaryFile is unlinked immediately; a disconnected stream or
    a packaging failure closes its descriptor, removing its disk usage.
    """
    inventory = _inventory(package_root, evidence_root)
    archive = tempfile.TemporaryFile(mode="w+b")
    try:
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for file, name, length in inventory:
                _append_verified_file(bundle, file, name, length)
        archive.flush()
        length = archive.seek(0, os.SEEK_END)
        if length > MAX_DELIVERY_SOURCE_BYTES + 8 * 1024 * 1024:
            raise ProjectDeliveryArchiveError(
                "Project delivery compressed archive is too large",
                status_code=413,
            )
        archive.seek(0)
        digest = hashlib.sha256()
        while data := archive.read(ARCHIVE_CHUNK_BYTES):
            digest.update(data)
        archive.seek(0)
        return ProjectDeliveryArchive(archive, length, digest.hexdigest())
    except BaseException:
        archive.close()
        raise
