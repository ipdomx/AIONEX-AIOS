"""Private companion backup and restore validation for local 3D assets."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
import hashlib
import hmac
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tarfile
import tempfile
import time
from typing import BinaryIO, cast
from uuid import uuid4

from app.core.config import Settings, settings
from app.services.backup_executor import BackupExecutionError

_DB_ARTIFACT = re.compile(r"backup-[0-9a-f]{24}(?:-[0-9a-f]{32})?\.dump")
_SNAPSHOT_ARTIFACT = re.compile(
    r"backup-[0-9a-f]{24}(?:-[0-9a-f]{32})?\.three-d\.tar"
)
_PARTIAL_ARTIFACT = re.compile(
    r"\.backup-[0-9a-f]{24}(?:-[0-9a-f]{32})?\.three-d\.tar"
    r"\.[0-9a-f]{32}\.partial"
)
_SCHEMA_VERSION = 1
_MAX_FILES = 100_000
_MAX_MANIFEST_BYTES = 16 * 1024 * 1024
_CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True, slots=True)
class ThreeDAssetSnapshot:
    location: str
    checksum: str
    size_bytes: int
    file_count: int
    payload_bytes: int


@dataclass(frozen=True, slots=True)
class _SourceFile:
    relative: str
    path: Path
    size_bytes: int
    inode: int
    mtime_ns: int


class _HashingReader:
    def __init__(self, stream: BinaryIO) -> None:
        self.stream = stream
        self.digest = hashlib.sha256()
        self.count = 0

    def read(self, size: int = -1) -> bytes:
        chunk = self.stream.read(size)
        if chunk:
            self.digest.update(chunk)
            self.count += len(chunk)
        return chunk


class ThreeDAssetSnapshotExecutor:
    """Create and validate immutable companion archives for local 3D assets."""

    def __init__(self, config: Settings = settings) -> None:
        self._settings = config
        self.enabled = bool(config.BACKUP_THREE_D_ASSETS_ENABLED)
        self._source = Path(config.THREE_D_STORAGE_ROOT)
        self._backup_dir = Path(config.BACKUP_DIR)

    @staticmethod
    def _sync_directory(directory: Path) -> None:
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _protected_backup_dir(self) -> Path:
        try:
            metadata = self._backup_dir.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise OSError("backup directory is unsafe")
            return self._backup_dir.resolve(strict=True)
        except OSError as exc:
            raise BackupExecutionError(
                "3D asset backup storage",
                "The protected backup location is unavailable for 3D assets",
            ) from exc

    def _cleanup_directory(self) -> Path | None:
        if not self._backup_dir.exists() and not self._backup_dir.is_symlink():
            return None
        return self._protected_backup_dir()

    def _protected_source(self) -> Path:
        if not self.enabled:
            raise BackupExecutionError(
                "3D asset backup",
                "Local 3D asset backup is not enabled",
                status_code=409,
            )
        try:
            metadata = self._source.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise OSError("3D asset root is unsafe")
            root = self._source.resolve(strict=True)
            if stat.S_IMODE(root.stat().st_mode) & 0o077:
                raise OSError("3D asset root is not private")
            if not os.access(root, os.R_OK | os.X_OK):
                raise OSError("3D asset root is unreadable")
            return root
        except OSError as exc:
            raise BackupExecutionError(
                "3D asset backup",
                "The private 3D asset volume is unavailable",
            ) from exc

    def verify_source(self) -> None:
        if self.enabled:
            self._protected_source()

    def _companion_path(self, database_location: str) -> Path:
        backup_dir = self._protected_backup_dir()
        database = Path(database_location)
        if not _DB_ARTIFACT.fullmatch(database.name):
            raise BackupExecutionError(
                "3D asset backup",
                "The database backup path is not worker-managed",
                status_code=409,
            )
        try:
            if database.parent.resolve(strict=True) != backup_dir:
                raise OSError("database backup is outside protected storage")
        except OSError as exc:
            raise BackupExecutionError(
                "3D asset backup",
                "The database backup is outside protected storage",
                status_code=409,
            ) from exc
        return backup_dir / f"{database.name[:-5]}.three-d.tar"

    @staticmethod
    def _safe_relative(value: str) -> PurePosixPath:
        relative = PurePosixPath(value)
        if (
            not value
            or relative.is_absolute()
            or ".." in relative.parts
            or "." in relative.parts
            or len(value.encode("utf-8")) > 1024
        ):
            raise BackupExecutionError(
                "3D asset backup",
                "A 3D asset path is unsafe",
            )
        return relative

    def _source_files(self) -> list[_SourceFile]:
        root = self._protected_source()
        result: list[_SourceFile] = []
        for current_text, directories, files in os.walk(root, followlinks=False):
            current = Path(current_text)
            for name in list(directories):
                candidate = current / name
                metadata = candidate.lstat()
                if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                    raise BackupExecutionError(
                        "3D asset backup",
                        "The private 3D asset tree contains an unsafe directory",
                    )
                if stat.S_IMODE(metadata.st_mode) & 0o077:
                    raise BackupExecutionError(
                        "3D asset backup",
                        "The private 3D asset tree has unsafe directory permissions",
                    )
            for name in files:
                if name.startswith(".") and name.endswith(".partial"):
                    continue
                candidate = current / name
                metadata = candidate.lstat()
                if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                    raise BackupExecutionError(
                        "3D asset backup",
                        "The private 3D asset tree contains an unsafe file",
                    )
                if stat.S_IMODE(metadata.st_mode) & 0o077:
                    raise BackupExecutionError(
                        "3D asset backup",
                        "The private 3D asset tree has unsafe file permissions",
                    )
                relative = candidate.relative_to(root).as_posix()
                self._safe_relative(relative)
                result.append(
                    _SourceFile(
                        relative=relative,
                        path=candidate,
                        size_bytes=metadata.st_size,
                        inode=metadata.st_ino,
                        mtime_ns=metadata.st_mtime_ns,
                    )
                )
                if len(result) > _MAX_FILES:
                    raise BackupExecutionError(
                        "3D asset backup",
                        "The 3D asset snapshot exceeds the supported file count",
                    )
        result.sort(key=lambda item: item.relative)
        return result

    def source_size_bytes(self) -> int:
        if not self.enabled:
            return 0
        return sum(item.size_bytes for item in self._source_files())

    def estimated_snapshot_bytes(self) -> int:
        """Return a conservative tar-capacity estimate for the current tree."""

        if not self.enabled:
            return 0
        files = self._source_files()
        payload_and_headers = sum(
            512 + ((item.size_bytes + 511) // 512) * 512 for item in files
        )
        return payload_and_headers + 512 + _MAX_MANIFEST_BYTES + 10_240

    @staticmethod
    def _archive_checksum(path: Path) -> tuple[str, int]:
        digest = hashlib.sha256()
        size_bytes = 0
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise OSError("snapshot is not a regular file")
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                for chunk in iter(lambda: stream.read(_CHUNK_SIZE), b""):
                    digest.update(chunk)
                    size_bytes += len(chunk)
        finally:
            os.close(descriptor)
        return digest.hexdigest(), size_bytes

    def create_snapshot(self, database_location: str) -> ThreeDAssetSnapshot | None:
        if not self.enabled:
            return None
        destination = self._companion_path(database_location)
        if destination.exists():
            return self.validate_snapshot(database_location)
        files = self._source_files()
        temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.partial")
        manifest_files: list[dict[str, object]] = []
        payload_bytes = 0
        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            with os.fdopen(descriptor, "wb", closefd=True) as output:
                with tarfile.open(
                    fileobj=output,
                    mode="w",
                    format=tarfile.PAX_FORMAT,
                ) as archive:
                    for source_item in files:
                        source_descriptor = os.open(
                            source_item.path,
                            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                        )
                        try:
                            before = os.fstat(source_descriptor)
                            if (
                                not stat.S_ISREG(before.st_mode)
                                or before.st_ino != source_item.inode
                                or before.st_size != source_item.size_bytes
                                or before.st_mtime_ns != source_item.mtime_ns
                            ):
                                raise BackupExecutionError(
                                    "3D asset backup",
                                    "A 3D asset changed while the snapshot was being created",
                                )
                            with os.fdopen(
                                source_descriptor,
                                "rb",
                                closefd=False,
                            ) as source:
                                reader = _HashingReader(source)
                                info = tarfile.TarInfo(
                                    f"files/{source_item.relative}"
                                )
                                info.size = before.st_size
                                info.mode = 0o600
                                info.mtime = 0
                                info.uid = 0
                                info.gid = 0
                                info.uname = ""
                                info.gname = ""
                                archive.addfile(info, cast(BinaryIO, reader))
                            after = os.fstat(source_descriptor)
                            if (
                                reader.count != source_item.size_bytes
                                or after.st_ino != source_item.inode
                                or after.st_size != source_item.size_bytes
                                or after.st_mtime_ns != source_item.mtime_ns
                            ):
                                raise BackupExecutionError(
                                    "3D asset backup",
                                    "A 3D asset changed while the snapshot was being created",
                                )
                            manifest_files.append(
                                {
                                    "path": source_item.relative,
                                    "sha256": reader.digest.hexdigest(),
                                    "size_bytes": reader.count,
                                }
                            )
                            payload_bytes += reader.count
                        finally:
                            os.close(source_descriptor)
                    manifest = json.dumps(
                        {
                            "schema_version": _SCHEMA_VERSION,
                            "kind": "aionex-three-d-local-assets",
                            "file_count": len(manifest_files),
                            "payload_bytes": payload_bytes,
                            "files": manifest_files,
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                    if len(manifest) > _MAX_MANIFEST_BYTES:
                        raise BackupExecutionError(
                            "3D asset backup",
                            "The 3D asset snapshot manifest is too large",
                        )
                    info = tarfile.TarInfo("manifest.json")
                    info.size = len(manifest)
                    info.mode = 0o600
                    info.mtime = 0
                    archive.addfile(info, io.BytesIO(manifest))
                output.flush()
                os.fsync(output.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, destination)
            self._sync_directory(destination.parent)
            checksum, size_bytes = self._archive_checksum(destination)
            return ThreeDAssetSnapshot(
                location=str(destination),
                checksum=checksum,
                size_bytes=size_bytes,
                file_count=len(manifest_files),
                payload_bytes=payload_bytes,
            )
        except BackupExecutionError:
            raise
        except (OSError, tarfile.TarError) as exc:
            raise BackupExecutionError(
                "3D asset backup",
                "The 3D asset snapshot could not be finalized",
            ) from exc
        finally:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)

    def validate_snapshot(
        self,
        database_location: str,
        *,
        expected_checksum: str | None = None,
        expected_size_bytes: int | None = None,
        expected_file_count: int | None = None,
        expected_payload_bytes: int | None = None,
    ) -> ThreeDAssetSnapshot:
        destination = self._companion_path(database_location)
        try:
            metadata = destination.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                raise OSError("snapshot is unsafe")
            if stat.S_IMODE(metadata.st_mode) & 0o077:
                raise OSError("snapshot permissions are unsafe")
            checksum, size_bytes = self._archive_checksum(destination)
            if expected_checksum and not hmac.compare_digest(
                checksum, expected_checksum
            ):
                raise BackupExecutionError(
                    "3D asset restore validation",
                    "The 3D asset snapshot checksum does not match durable evidence",
                    status_code=409,
                )
            if (
                expected_size_bytes is not None
                and size_bytes != int(expected_size_bytes)
            ):
                raise BackupExecutionError(
                    "3D asset restore validation",
                    "The 3D asset snapshot size does not match durable evidence",
                    status_code=409,
                )
            backup_dir = self._protected_backup_dir()
            descriptor = os.open(
                destination,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            )
            try:
                with os.fdopen(descriptor, "rb", closefd=False) as archive_stream:
                    with tarfile.open(fileobj=archive_stream, mode="r:") as archive:
                        result = self._validate_archive_members(
                            archive,
                            backup_dir,
                            expected_file_count=expected_file_count,
                            expected_payload_bytes=expected_payload_bytes,
                        )
            finally:
                os.close(descriptor)
            return ThreeDAssetSnapshot(
                location=str(destination),
                checksum=checksum,
                size_bytes=size_bytes,
                file_count=result[0],
                payload_bytes=result[1],
            )
        except BackupExecutionError:
            raise
        except (OSError, tarfile.TarError, ValueError) as exc:
            raise BackupExecutionError(
                "3D asset restore validation",
                "The protected 3D asset snapshot failed integrity validation",
                status_code=409,
            ) from exc

    def _validate_archive_members(
        self,
        archive: tarfile.TarFile,
        backup_dir: Path,
        *,
        expected_file_count: int | None,
        expected_payload_bytes: int | None,
    ) -> tuple[int, int]:
        members = archive.getmembers()
        if not members or len(members) > _MAX_FILES + 1:
            raise BackupExecutionError(
                "3D asset restore validation",
                "The 3D asset snapshot member count is invalid",
            )
        by_name: dict[str, tarfile.TarInfo] = {}
        for member in members:
            if member.name in by_name or not member.isfile():
                raise BackupExecutionError(
                    "3D asset restore validation",
                    "The 3D asset snapshot contains an unsafe member",
                )
            by_name[member.name] = member
        manifest_member = by_name.get("manifest.json")
        if manifest_member is None or manifest_member.size > _MAX_MANIFEST_BYTES:
            raise BackupExecutionError(
                "3D asset restore validation",
                "The 3D asset snapshot manifest is invalid",
            )
        manifest_stream = archive.extractfile(manifest_member)
        if manifest_stream is None:
            raise BackupExecutionError(
                "3D asset restore validation",
                "The 3D asset snapshot manifest is unreadable",
            )
        raw_manifest = manifest_stream.read(_MAX_MANIFEST_BYTES + 1)
        if len(raw_manifest) > _MAX_MANIFEST_BYTES:
            raise BackupExecutionError(
                "3D asset restore validation",
                "The 3D asset snapshot manifest is too large",
            )
        try:
            manifest = json.loads(raw_manifest)
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as exc:
            raise BackupExecutionError(
                "3D asset restore validation",
                "The 3D asset snapshot manifest is invalid",
            ) from exc
        if (
            not isinstance(manifest, dict)
            or manifest.get("schema_version") != _SCHEMA_VERSION
            or manifest.get("kind") != "aionex-three-d-local-assets"
        ):
            raise BackupExecutionError(
                "3D asset restore validation",
                "The 3D asset snapshot manifest is invalid",
            )
        files = manifest.get("files")
        if not isinstance(files, list) or len(files) > _MAX_FILES:
            raise BackupExecutionError(
                "3D asset restore validation",
                "The 3D asset snapshot manifest is invalid",
            )
        if manifest.get("file_count") != len(files):
            raise BackupExecutionError(
                "3D asset restore validation",
                "The 3D asset snapshot file count is invalid",
            )
        if expected_file_count is not None and len(files) != int(expected_file_count):
            raise BackupExecutionError(
                "3D asset restore validation",
                "The 3D asset snapshot file count does not match durable evidence",
                status_code=409,
            )
        expected_names = {"manifest.json"}
        manifest_paths: set[str] = set()
        payload_bytes = 0
        with tempfile.TemporaryDirectory(
            prefix=".three-d-restore-",
            dir=backup_dir,
        ) as scratch_text:
            scratch = Path(scratch_text)
            os.chmod(scratch, 0o700)
            for entry in files:
                if not isinstance(entry, dict):
                    raise BackupExecutionError(
                        "3D asset restore validation",
                        "The 3D asset snapshot manifest is invalid",
                    )
                relative_text = str(entry.get("path", ""))
                relative = self._safe_relative(relative_text)
                if relative_text in manifest_paths:
                    raise BackupExecutionError(
                        "3D asset restore validation",
                        "The 3D asset snapshot manifest contains duplicate paths",
                    )
                manifest_paths.add(relative_text)
                member_name = f"files/{relative.as_posix()}"
                expected_names.add(member_name)
                file_member = by_name.get(member_name)
                try:
                    expected_size = int(entry["size_bytes"])
                    expected_hash = str(entry["sha256"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise BackupExecutionError(
                        "3D asset restore validation",
                        "The 3D asset snapshot manifest is invalid",
                    ) from exc
                if (
                    expected_size < 0
                    or file_member is None
                    or file_member.size != expected_size
                    or re.fullmatch(r"[0-9a-f]{64}", expected_hash) is None
                ):
                    raise BackupExecutionError(
                        "3D asset restore validation",
                        "The 3D asset snapshot member metadata is invalid",
                    )
                stream = archive.extractfile(file_member)
                if stream is None:
                    raise BackupExecutionError(
                        "3D asset restore validation",
                        "A 3D asset snapshot member is unreadable",
                    )
                target = scratch.joinpath(*relative.parts)
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                os.chmod(target.parent, 0o700)
                digest = hashlib.sha256()
                count = 0
                descriptor = os.open(
                    target,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                )
                try:
                    with os.fdopen(descriptor, "wb", closefd=False) as output:
                        while True:
                            remaining = expected_size - count
                            chunk = stream.read(min(_CHUNK_SIZE, remaining + 1))
                            if not chunk:
                                break
                            output.write(chunk)
                            digest.update(chunk)
                            count += len(chunk)
                            if count > expected_size:
                                break
                        output.flush()
                        os.fsync(output.fileno())
                finally:
                    os.close(descriptor)
                if count != expected_size or not hmac.compare_digest(
                    digest.hexdigest(), expected_hash
                ):
                    raise BackupExecutionError(
                        "3D asset restore validation",
                        "A restored 3D asset failed integrity verification",
                    )
                payload_bytes += count
        if set(by_name) != expected_names:
            raise BackupExecutionError(
                "3D asset restore validation",
                "The 3D asset snapshot contains unmanifested members",
            )
        if manifest.get("payload_bytes") != payload_bytes:
            raise BackupExecutionError(
                "3D asset restore validation",
                "The 3D asset snapshot payload size is invalid",
            )
        if (
            expected_payload_bytes is not None
            and payload_bytes != int(expected_payload_bytes)
        ):
            raise BackupExecutionError(
                "3D asset restore validation",
                "The 3D asset snapshot payload size does not match durable evidence",
                status_code=409,
            )
        return len(files), payload_bytes

    def cleanup_stale_partials(self, maximum_age_seconds: int) -> int:
        directory = self._cleanup_directory()
        if directory is None:
            return 0
        cutoff = time.time() - maximum_age_seconds
        removed = 0
        for candidate in directory.glob(".backup-*.three-d.tar.*.partial"):
            if not _PARTIAL_ARTIFACT.fullmatch(candidate.name):
                continue
            try:
                metadata = candidate.lstat()
                if (
                    stat.S_ISLNK(metadata.st_mode)
                    or not stat.S_ISREG(metadata.st_mode)
                    or metadata.st_mtime > cutoff
                ):
                    continue
                candidate.unlink()
                removed += 1
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise BackupExecutionError(
                    "3D asset backup cleanup",
                    "An abandoned 3D asset snapshot partial could not be removed safely",
                ) from exc
        if removed:
            self._sync_directory(directory)
        return removed

    def cleanup_backup_partials(self, backup_id: str) -> int:
        directory = self._cleanup_directory()
        if directory is None:
            return 0
        stable = hashlib.sha256(backup_id.encode("utf-8")).hexdigest()[:24]
        removed = 0
        for candidate in directory.glob(f".backup-{stable}-*.three-d.tar.*.partial"):
            if not _PARTIAL_ARTIFACT.fullmatch(candidate.name):
                continue
            try:
                metadata = candidate.lstat()
                if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                    continue
                candidate.unlink()
                removed += 1
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise BackupExecutionError(
                    "3D asset backup cleanup",
                    "An abandoned 3D asset snapshot partial could not be removed safely",
                ) from exc
        if removed:
            self._sync_directory(directory)
        return removed

    def delete_snapshot(self, database_location: str) -> bool:
        if not self.enabled:
            return False
        destination = self._companion_path(database_location)
        try:
            metadata = destination.lstat()
            if (
                stat.S_ISLNK(metadata.st_mode)
                or not stat.S_ISREG(metadata.st_mode)
                or not _SNAPSHOT_ARTIFACT.fullmatch(destination.name)
            ):
                raise OSError("snapshot is unsafe")
            destination.unlink()
            self._sync_directory(destination.parent)
            return True
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise BackupExecutionError(
                "3D asset backup retention",
                "The expired 3D asset snapshot could not be removed safely",
            ) from exc

    def cleanup_orphan_snapshots(self, maximum_age_seconds: int) -> int:
        directory = self._cleanup_directory()
        if directory is None:
            return 0
        cutoff = time.time() - maximum_age_seconds
        removed = 0
        for candidate in directory.glob("backup-*.three-d.tar"):
            if not _SNAPSHOT_ARTIFACT.fullmatch(candidate.name):
                continue
            database = candidate.with_name(
                candidate.name.replace(".three-d.tar", ".dump")
            )
            try:
                metadata = candidate.lstat()
                if (
                    stat.S_ISLNK(metadata.st_mode)
                    or not stat.S_ISREG(metadata.st_mode)
                    or metadata.st_mtime > cutoff
                    or database.exists()
                ):
                    continue
                candidate.unlink()
                removed += 1
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise BackupExecutionError(
                    "3D asset backup cleanup",
                    "An orphaned 3D asset snapshot could not be removed safely",
                ) from exc
        if removed:
            self._sync_directory(directory)
        return removed
