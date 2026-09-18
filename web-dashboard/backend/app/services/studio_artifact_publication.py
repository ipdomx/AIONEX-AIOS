"""Publish one complete Studio archive without replacing an existing entry.

The process owns a randomly named staging file under pinned directory descriptors.
A same-directory link publishes its fully flushed bytes with no replace fallback.
Only the identity-checked staging name is removed; a final name is never deleted
here, even when publication or a directory sync has an uncertain outcome.

This is local publication, not durable execution-resource ownership, worker
settlement or host-drain evidence. Cooperating service processes are trusted not
to maliciously race directory entries after identity checks; same-UID/root
attackers and later path-based readers/cleanup require separate containment.
"""
from __future__ import annotations

from contextlib import ExitStack
import hashlib
import os
from pathlib import Path
import stat
from uuid import uuid4

_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE_FLAGS = os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
_CHUNK = 1024 * 1024


class StudioPublicationUncertain(RuntimeError):
    """Publication, path identity or private staging cleanup was not proven."""


def _component(value: str) -> str:
    if (
        not isinstance(value, str) or not value or value in {".", ".."}
        or "/" in value or "\\" in value
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
        or len(value.encode("utf-8")) > 220
    ):
        raise ValueError("Invalid Studio storage component")
    return value


def _identity(value: os.stat_result) -> tuple[int, int]:
    return value.st_dev, value.st_ino


def _open_directory(parent: int, name: str, *, create: bool) -> int:
    if create:
        try:
            os.mkdir(name, mode=0o700, dir_fd=parent)
        except FileExistsError:
            # Open below without following a symlink; never alter its permissions.
            return os.open(name, _DIRECTORY_FLAGS, dir_fd=parent)
        os.fsync(parent)
    return os.open(name, _DIRECTORY_FLAGS, dir_fd=parent)


def _assert_tree(edges: list[tuple[int, str, int]]) -> None:
    for parent, name, descriptor in edges:
        current = os.stat(name, dir_fd=parent, follow_symlinks=False)
        pinned = os.fstat(descriptor)
        if not stat.S_ISDIR(current.st_mode) or _identity(current) != _identity(pinned):
            raise StudioPublicationUncertain("Studio storage directory identity changed")


def _assert_file(
    directory: int, name: str, descriptor: int, *, links: int, size: int,
) -> None:
    current = os.stat(name, dir_fd=directory, follow_symlinks=False)
    pinned = os.fstat(descriptor)
    if (
        not stat.S_ISREG(current.st_mode) or _identity(current) != _identity(pinned)
        or current.st_nlink != links or pinned.st_nlink != links
        or current.st_uid != os.geteuid() or stat.S_IMODE(current.st_mode) != 0o600
        or current.st_size != size or pinned.st_size != size
    ):
        raise StudioPublicationUncertain("Studio archive identity is unverified")


def _write_bytes(descriptor: int, content: bytes) -> None:
    remaining = memoryview(content)
    while remaining:
        count = os.write(descriptor, remaining[:_CHUNK])
        if count <= 0:
            raise OSError("Studio archive write made no progress")
        remaining = remaining[count:]


def _verify_bytes(descriptor: int, checksum: str) -> None:
    os.lseek(descriptor, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    while chunk := os.read(descriptor, _CHUNK):
        digest.update(chunk)
    if digest.hexdigest() != checksum:
        raise StudioPublicationUncertain("Studio staged archive checksum differs")


def _remove_staging(directory: int, name: str, descriptor: int) -> None:
    """Never follow a new pathname or delete a final/archive name on failure."""
    current = os.stat(name, dir_fd=directory, follow_symlinks=False)
    pinned = os.fstat(descriptor)
    if (
        not stat.S_ISREG(current.st_mode) or _identity(current) != _identity(pinned)
        or current.st_nlink not in {1, 2}
    ):
        raise StudioPublicationUncertain("Studio staging ownership changed")
    os.unlink(name, dir_fd=directory)
    os.fsync(directory)


def publish_studio_archive(
    *, root: str | Path, organization_id: str, asset_id: str,
    revision_number: int, filename: str, content: bytes, checksum: str,
    size_bytes: int, maximum_bytes: int,
) -> Path:
    """Return a path only after no-replace publication and local verification.

    Invalid inputs are rejected before filesystem mutation. Existing destination
    entries, including identical archives or unsafe links, always cause failure.
    A crash after link can leave two names; recovery must inspect them, not replay
    the job or infer cleanup from this function's absence.
    """
    organization_id, asset_id, filename = (
        _component(value) for value in (organization_id, asset_id, filename)
    )
    if type(revision_number) is not int or not 1 <= revision_number <= 2_147_483_647:
        raise ValueError("Invalid Studio revision number")
    if (
        not isinstance(content, bytes) or type(size_bytes) is not int
        or size_bytes != len(content) or size_bytes <= 0
        or type(maximum_bytes) is not int or not 0 < size_bytes <= maximum_bytes
        or not isinstance(checksum, str) or hashlib.sha256(content).hexdigest() != checksum
    ):
        raise ValueError("Studio archive payload metadata is inconsistent")
    configured = Path(root)
    if ".." in configured.parts:
        raise ValueError("Invalid Studio root")
    # Lexical absolutization only. No resolve() that would accept a symlink.
    absolute_root = Path(os.path.abspath(configured))
    root_parts = absolute_root.parts[1:]
    if not root_parts:
        raise ValueError("Studio root cannot be the filesystem root")
    components = (*root_parts, organization_id, asset_id, f"revision-{revision_number}")
    edges: list[tuple[int, str, int]] = []
    with ExitStack() as stack:
        directory = os.open("/", _DIRECTORY_FLAGS)
        stack.callback(os.close, directory)
        for index, name in enumerate(components):
            name = _component(name)
            child = _open_directory(directory, name, create=True)
            stack.callback(os.close, child)
            if index >= len(root_parts) - 1:
                current = os.fstat(child)
                if current.st_uid != os.geteuid() or stat.S_IMODE(current.st_mode) & 0o022:
                    raise StudioPublicationUncertain("Studio storage directory is not private to its writer")
            edges.append((directory, name, child))
            directory = child
        _assert_tree(edges)
        staging_name = f".studio-publish-{uuid4().hex}.partial"
        descriptor = os.open(staging_name, _FILE_FLAGS, 0o600, dir_fd=directory)
        stack.callback(os.close, descriptor)
        try:
            os.fchmod(descriptor, 0o600)
            _assert_file(directory, staging_name, descriptor, links=1, size=0)
            _write_bytes(descriptor, content)
            os.fsync(descriptor)
            _verify_bytes(descriptor, checksum)
            _assert_file(directory, staging_name, descriptor, links=1, size=size_bytes)
            _assert_tree(edges)
            # Atomic name creation, never exists()+replace() and no fallback.
            os.link(
                staging_name, filename, src_dir_fd=directory, dst_dir_fd=directory,
                follow_symlinks=False,
            )
            os.fsync(directory)
            _assert_file(directory, filename, descriptor, links=2, size=size_bytes)
            _assert_tree(edges)
        finally:
            # A cleanup error is propagated. Never manufacture clean success,
            # and never delete the destination after a possibly completed link.
            _remove_staging(directory, staging_name, descriptor)
        _assert_file(directory, filename, descriptor, links=1, size=size_bytes)
        _assert_tree(edges)
    return absolute_root / organization_id / asset_id / f"revision-{revision_number}" / filename
