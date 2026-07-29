"""Production PostgreSQL backup and restore-validation execution.

The executor deliberately invokes PostgreSQL client programs with discrete
connection arguments.  Passwords are provided only through ``PGPASSWORD`` and
are never included in command lines, exceptions, audit payloads, or logs.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol, Sequence
from uuid import uuid4

from app.core.config import Settings, settings
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession


class BackupExecutionError(RuntimeError):
    """A sanitized operational failure safe to expose to an authenticated owner."""

    def __init__(self, operation: str, message: str, *, status_code: int = 503):
        super().__init__(message)
        self.operation = operation
        self.public_message = message
        self.status_code = status_code


@dataclass(frozen=True)
class BackupArtifact:
    """A completed immutable backup artifact."""

    location: str
    checksum: str
    size_bytes: int


@dataclass(frozen=True)
class RestoreValidation:
    """Evidence returned only after a full restore into an isolated database."""

    checksum: str
    size_bytes: int
    restored: bool = True


@dataclass(frozen=True)
class _DatabaseTarget:
    host: str
    port: int
    username: str
    password: str
    database: str
    sslmode: str | None = None


class CommandRunner(Protocol):
    """Injectable subprocess boundary used by deterministic unit tests."""

    async def run(
        self,
        command: Sequence[str],
        *,
        environment: Mapping[str, str],
        timeout_seconds: int,
        operation: str,
    ) -> None: ...


class AsyncPostgresCommandRunner:
    """Run PostgreSQL utilities without a shell and with bounded execution time."""

    @staticmethod
    async def _terminate(process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        try:
            process.terminate()
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(process.communicate(), timeout=5)
        except TimeoutError:
            process.kill()
            await process.communicate()

    async def run(
        self,
        command: Sequence[str],
        *,
        environment: Mapping[str, str],
        timeout_seconds: int,
        operation: str,
    ) -> None:
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
                env=dict(environment),
            )
        except FileNotFoundError as exc:
            raise BackupExecutionError(
                operation,
                f"{operation} could not start because a PostgreSQL client utility "
                "is unavailable",
            ) from exc
        except OSError as exc:
            raise BackupExecutionError(
                operation,
                f"{operation} could not start",
            ) from exc

        try:
            _, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout_seconds,
            )
        except asyncio.CancelledError:
            await self._terminate(process)
            raise
        except TimeoutError as exc:
            process.kill()
            await process.communicate()
            raise BackupExecutionError(
                operation,
                f"{operation} exceeded its {timeout_seconds}-second safety timeout",
                status_code=504,
            ) from exc
        if process.returncode != 0:
            # PostgreSQL diagnostics can include connection identifiers and
            # restored data.  Keep them out of responses and persisted audits.
            del stderr
            raise BackupExecutionError(
                operation,
                f"{operation} failed with PostgreSQL client exit code "
                f"{process.returncode}",
            )


async def acquire_enqueue_lock(session: AsyncSession, key: str) -> None:
    """Serialize a short enqueue transaction across all API workers.

    PostgreSQL advisory transaction locks cover the otherwise racy
    "check-active-then-insert" window.  Non-PostgreSQL fake/test sessions are
    intentionally a no-op; production Settings only support PostgreSQL.
    """

    get_bind = getattr(session, "get_bind", None)
    if not callable(get_bind):
        return
    bind = get_bind()
    if getattr(getattr(bind, "dialect", None), "name", None) != "postgresql":
        return
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"aionex-backup-job:{key}"},
    )


class BackupExecutor:
    """Create atomic custom-format dumps and prove they can be restored."""

    def __init__(
        self,
        config: Settings = settings,
        runner: CommandRunner | None = None,
    ) -> None:
        self._settings = config
        self._runner = runner or AsyncPostgresCommandRunner()
        self._target = self._database_target(config)
        self._backup_dir = Path(config.BACKUP_DIR)

    @staticmethod
    def _database_target(config: Settings) -> _DatabaseTarget:
        url = make_url(config.DATABASE_URL)
        if not url.drivername.startswith("postgresql"):
            raise BackupExecutionError(
                "backup configuration",
                "Backups require the application database to be PostgreSQL",
                status_code=409,
            )
        if not all((url.host, url.username, url.database)):
            raise BackupExecutionError(
                "backup configuration",
                "The PostgreSQL backup connection is incomplete",
                status_code=500,
            )
        query = dict(url.query)
        sslmode = query.get("sslmode") or query.get("ssl")
        return _DatabaseTarget(
            host=str(url.host),
            port=int(url.port or 5432),
            username=str(url.username),
            password=str(url.password or ""),
            database=str(url.database),
            sslmode=str(sslmode) if sslmode else None,
        )

    def _secure_backup_directory(self) -> Path:
        try:
            self._backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            metadata = self._backup_dir.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise BackupExecutionError(
                    "backup storage",
                    "The configured backup location is not a secure directory",
                    status_code=500,
                )
            os.chmod(self._backup_dir, 0o700)
            return self._backup_dir.resolve(strict=True)
        except BackupExecutionError:
            raise
        except OSError as exc:
            raise BackupExecutionError(
                "backup storage",
                "The configured backup location is not writable",
                status_code=500,
            ) from exc

    @property
    def _heartbeat_path(self) -> Path:
        hostname = os.environ.get("HOSTNAME", "local-worker")
        identity = hashlib.sha256(hostname.encode("utf-8")).hexdigest()[:16]
        return self._secure_backup_directory() / f".worker-{identity}.heartbeat"

    def verify_storage(self) -> None:
        """Fail unless the protected volume is writable by the worker user."""

        directory = self._secure_backup_directory()
        probe = directory / f".storage-probe-{uuid4().hex}"
        descriptor: int | None = None
        try:
            descriptor = os.open(
                probe,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            os.write(descriptor, b"ready")
            os.fsync(descriptor)
        except OSError as exc:
            raise BackupExecutionError(
                "backup storage",
                "The protected backup volume is not writable",
                status_code=500,
            ) from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
            try:
                probe.unlink(missing_ok=True)
            except OSError:
                pass

    def write_heartbeat(self) -> None:
        """Atomically publish liveness for this specific worker container."""

        destination = self._heartbeat_path
        temporary = destination.with_name(f"{destination.name}.{uuid4().hex}.tmp")
        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            try:
                os.write(descriptor, f"{time.time():.6f}\n".encode("ascii"))
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            os.replace(temporary, destination)
            self._sync_directory(destination.parent)
        except OSError as exc:
            raise BackupExecutionError(
                "backup worker heartbeat",
                "The backup worker heartbeat could not be persisted",
                status_code=500,
            ) from exc
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def verify_heartbeat(self) -> None:
        """Fail when the main worker loop has stopped publishing liveness."""

        heartbeat = self._heartbeat_path
        try:
            metadata = heartbeat.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                raise OSError("heartbeat is not a regular file")
            maximum_age = max(
                60,
                5 * self._settings.BACKUP_WORKER_HEARTBEAT_SECONDS,
            )
            if time.time() - metadata.st_mtime > maximum_age:
                raise OSError("heartbeat is stale")
        except OSError as exc:
            raise BackupExecutionError(
                "backup worker heartbeat",
                "The backup worker heartbeat is missing or stale",
                status_code=503,
            ) from exc

    def _environment(self) -> dict[str, str]:
        environment = {
            key: os.environ[key]
            for key in ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TZ")
            if key in os.environ
        }
        environment["PGPASSWORD"] = self._target.password
        environment["PGAPPNAME"] = "aionex-backup-executor"
        if self._target.sslmode:
            environment["PGSSLMODE"] = self._target.sslmode
        return environment

    def _connection_arguments(self) -> list[str]:
        return [
            "--host",
            self._target.host,
            "--port",
            str(self._target.port),
            "--username",
            self._target.username,
            "--no-password",
        ]

    @staticmethod
    def _inspect_artifact(
        path: Path,
        *,
        calculate_checksum: bool,
    ) -> tuple[str | None, int]:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
        except OSError as exc:
            raise BackupExecutionError(
                "backup integrity validation",
                "The backup artifact cannot be read safely",
            ) from exc

        digest = hashlib.sha256() if calculate_checksum else None
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise BackupExecutionError(
                    "backup integrity validation",
                    "The backup artifact is not a regular file",
                )
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                header = stream.read(5)
                if header != b"PGDMP":
                    raise BackupExecutionError(
                        "backup integrity validation",
                        "The backup artifact is not a PostgreSQL custom archive",
                    )
                if digest is not None:
                    digest.update(header)
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
            return (
                digest.hexdigest() if digest is not None else None,
                metadata.st_size,
            )
        finally:
            os.close(descriptor)

    @classmethod
    def _checksum(cls, path: Path) -> tuple[str, int]:
        checksum, size_bytes = cls._inspect_artifact(
            path,
            calculate_checksum=True,
        )
        if checksum is None:  # pragma: no cover - guaranteed by the call above
            raise AssertionError("checksum calculation did not produce a digest")
        return checksum, size_bytes

    @staticmethod
    def _sync_directory(directory: Path) -> None:
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    async def create_backup(self, backup_id: str) -> BackupArtifact:
        """Write one custom-format dump atomically and return integrity metadata."""

        directory = self._secure_backup_directory()
        stable_name = hashlib.sha256(backup_id.encode("utf-8")).hexdigest()[:24]
        destination = directory / f"backup-{stable_name}.dump"
        temporary = directory / f".backup-{stable_name}-{uuid4().hex}.partial"
        if destination.exists():
            checksum, size_bytes = self._checksum(destination)
            os.chmod(destination, 0o600, follow_symlinks=False)
            return BackupArtifact(
                location=str(destination),
                checksum=checksum,
                size_bytes=size_bytes,
            )
        descriptor: int | None = None
        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            os.close(descriptor)
            descriptor = None
            await self._runner.run(
                [
                    "pg_dump",
                    *self._connection_arguments(),
                    "--dbname",
                    self._target.database,
                    "--format=custom",
                    "--compress=6",
                    "--no-owner",
                    "--no-privileges",
                    "--file",
                    str(temporary),
                ],
                environment=self._environment(),
                timeout_seconds=self._settings.BACKUP_TIMEOUT_SECONDS,
                operation="PostgreSQL backup",
            )
            checksum, size_bytes = self._checksum(temporary)
            if size_bytes <= 5:
                raise BackupExecutionError(
                    "PostgreSQL backup",
                    "PostgreSQL produced an empty backup archive",
                )
            os.chmod(temporary, 0o600)
            with temporary.open("rb") as stream:
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
            self._sync_directory(directory)
            return BackupArtifact(
                location=str(destination),
                checksum=checksum,
                size_bytes=size_bytes,
            )
        except BackupExecutionError:
            raise
        except OSError as exc:
            raise BackupExecutionError(
                "PostgreSQL backup",
                "The backup artifact could not be finalized",
            ) from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def verify_artifact(
        self,
        location: str,
        expected_checksum: str | None,
        expected_size_bytes: int | None,
        *,
        verify_checksum: bool = True,
    ) -> BackupArtifact:
        """Verify that a durable record still points to a protected artifact.

        Cheap readiness probes validate containment, file type, archive header,
        and exact size. Release and restore gates additionally hash the complete
        archive. Callers must move this blocking filesystem work off an async
        event loop for potentially large artifacts.
        """

        directory = self._secure_backup_directory()
        candidate = Path(location)
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(directory)
        except (OSError, ValueError) as exc:
            raise BackupExecutionError(
                "backup integrity validation",
                "The backup artifact is missing or outside the protected backup "
                "location",
                status_code=409,
            ) from exc
        checksum, size_bytes = self._inspect_artifact(
            resolved,
            calculate_checksum=verify_checksum,
        )
        if (
            expected_size_bytes is None
            or expected_size_bytes <= 5
            or size_bytes != expected_size_bytes
        ):
            raise BackupExecutionError(
                "backup integrity validation",
                "The backup artifact size does not match its durable record",
                status_code=409,
            )
        if not expected_checksum:
            raise BackupExecutionError(
                "backup integrity validation",
                "The backup artifact has no durable checksum",
                status_code=409,
            )
        if verify_checksum and (
            checksum is None or not hmac.compare_digest(checksum, expected_checksum)
        ):
            raise BackupExecutionError(
                "backup integrity validation",
                "The backup artifact checksum does not match its durable record",
                status_code=409,
            )
        return BackupArtifact(
            location=str(resolved),
            checksum=checksum or expected_checksum,
            size_bytes=size_bytes,
        )

    def _validated_artifact(
        self,
        location: str,
        expected_checksum: str | None,
    ) -> tuple[Path, str, int]:
        # Restore callers created before size metadata became mandatory still
        # use this private boundary. Verify the checksum first, then return the
        # observed size to the restore evidence.
        directory = self._secure_backup_directory()
        candidate = Path(location)
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(directory)
        except (OSError, ValueError) as exc:
            raise BackupExecutionError(
                "restore validation",
                "The backup artifact is missing or outside the protected backup "
                "location",
                status_code=409,
            ) from exc
        checksum, size_bytes = self._checksum(resolved)
        if not expected_checksum or not hmac.compare_digest(
            checksum,
            expected_checksum,
        ):
            raise BackupExecutionError(
                "restore validation",
                "The backup artifact checksum does not match its durable record",
                status_code=409,
            )
        return resolved, checksum, size_bytes

    async def validate_restore(
        self,
        location: str,
        expected_checksum: str | None,
        validation_id: str | None = None,
        *,
        expected_size_bytes: int | None = None,
    ) -> RestoreValidation:
        """Restore an archive into a unique scratch database and remove it."""

        if expected_size_bytes is not None:
            verified = self.verify_artifact(
                location,
                expected_checksum,
                expected_size_bytes,
            )
            artifact = Path(verified.location)
            checksum = verified.checksum
            size_bytes = verified.size_bytes
        else:
            artifact, checksum, size_bytes = self._validated_artifact(
                location,
                expected_checksum,
            )
        scratch_token = validation_id or uuid4().hex
        scratch_hash = hashlib.sha256(scratch_token.encode("utf-8")).hexdigest()[:20]
        scratch_database = f"aionex_restore_{scratch_hash}"
        environment = self._environment()
        connection = self._connection_arguments()
        created = False
        primary_error: BackupExecutionError | None = None
        try:
            # A killed worker can leave only its deterministic scratch database
            # behind.  Remove that isolated database before retrying the job.
            await self._runner.run(
                [
                    "dropdb",
                    *connection,
                    "--maintenance-db",
                    self._target.database,
                    "--if-exists",
                    "--force",
                    scratch_database,
                ],
                environment=environment,
                timeout_seconds=self._settings.BACKUP_CLEANUP_TIMEOUT_SECONDS,
                operation="Stale restore validation cleanup",
            )
            await self._runner.run(
                [
                    "createdb",
                    *connection,
                    "--maintenance-db",
                    self._target.database,
                    scratch_database,
                ],
                environment=environment,
                timeout_seconds=self._settings.BACKUP_VALIDATION_TIMEOUT_SECONDS,
                operation="Restore validation database creation",
            )
            created = True
            await self._runner.run(
                [
                    "pg_restore",
                    *connection,
                    "--dbname",
                    scratch_database,
                    "--exit-on-error",
                    "--no-owner",
                    "--no-privileges",
                    str(artifact),
                ],
                environment=environment,
                timeout_seconds=self._settings.BACKUP_VALIDATION_TIMEOUT_SECONDS,
                operation="PostgreSQL restore validation",
            )
            await self._runner.run(
                [
                    "psql",
                    *connection,
                    "--no-psqlrc",
                    "--dbname",
                    scratch_database,
                    "--tuples-only",
                    "--no-align",
                    "--set",
                    "ON_ERROR_STOP=1",
                    "--command",
                    (
                        "DO $aionex$ BEGIN IF NOT EXISTS ("
                        "SELECT 1 FROM pg_catalog.pg_class c "
                        "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
                        "WHERE c.relkind IN ('r','p') "
                        "AND n.nspname NOT LIKE 'pg_%' "
                        "AND n.nspname <> 'information_schema') "
                        "THEN RAISE EXCEPTION 'restored archive has no user tables'; "
                        "END IF; END $aionex$"
                    ),
                ],
                environment=environment,
                timeout_seconds=self._settings.BACKUP_VALIDATION_TIMEOUT_SECONDS,
                operation="Restored database verification",
            )
        except BackupExecutionError as exc:
            primary_error = exc
        finally:
            if created:
                try:
                    await self._runner.run(
                        [
                            "dropdb",
                            *connection,
                            "--maintenance-db",
                            self._target.database,
                            "--if-exists",
                            "--force",
                            scratch_database,
                        ],
                        environment=environment,
                        timeout_seconds=self._settings.BACKUP_CLEANUP_TIMEOUT_SECONDS,
                        operation="Restore validation cleanup",
                    )
                except BackupExecutionError as cleanup_error:
                    if primary_error is None:
                        primary_error = cleanup_error
        if primary_error is not None:
            raise primary_error
        return RestoreValidation(
            checksum=checksum,
            size_bytes=size_bytes,
        )


def get_backup_executor() -> BackupExecutor:
    """Create an executor from current immutable application settings."""

    return BackupExecutor()
