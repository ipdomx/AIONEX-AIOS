"""Cloudflare R2 off-site backup replication and readback validation.

FR-05B2 encrypts every new database, platform-asset, and manifest object with
the versioned client-side envelope before it reaches R2. Credentials and the
encryption keyring remain separate private mounts. Legacy plaintext evidence is
accepted only through an explicit schema-v1 restore path until retention removes
those generations.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Any
from urllib.parse import urlparse

import boto3  # type: ignore[import-untyped]
from botocore.config import Config  # type: ignore[import-untyped]
from botocore.exceptions import BotoCoreError, ClientError  # type: ignore[import-untyped]

from app.core.config import Settings, settings
from app.services.backup_executor import BackupCleanupIncomplete, BackupExecutionError
from app.services.offsite_encryption import (
    EncryptionContext,
    EncryptedArtifact,
    OffsiteEncryption,
)
from app.services.three_d_asset_backup import ThreeDAssetSnapshot

_CHUNK = 1024 * 1024
_BUCKET = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_BACKUP_ID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-" r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_ALLOWED_KEYS = {
    "R2_BACKUP_ENDPOINT",
    "R2_BACKUP_BUCKET",
    "R2_BACKUP_ACCESS_KEY_ID",
    "R2_BACKUP_SECRET_ACCESS_KEY",
}
_ENCRYPTION_FIELDS = {
    "algorithm",
    "envelope_version",
    "key_id",
    "ciphertext_sha256",
    "ciphertext_size_bytes",
}


@dataclass(frozen=True, slots=True)
class OffsiteValidationArtifacts:
    database_location: str
    snapshot_location: str | None


def _sha256(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise OSError("artifact is not a single-link regular file")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            for chunk in iter(lambda: stream.read(_CHUNK), b""):
                digest.update(chunk)
                size += len(chunk)
    finally:
        os.close(descriptor)
    return digest.hexdigest(), size


def _close_quietly(descriptor: int | None) -> None:
    if descriptor is None:
        return
    try:
        os.close(descriptor)
    except OSError:
        return


def _write_private(path: Path, payload: bytes) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("private file write made no progress")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _valid_checksum(value: Any) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError("invalid checksum")
    return value


def _valid_size(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("invalid byte size")
    return value


class OffsiteBackupReplicator:
    def __init__(self, config: Settings = settings) -> None:
        self._settings = config
        self.enabled = bool(config.BACKUP_OFFSITE_ENABLED)
        self._prefix = config.BACKUP_OFFSITE_PREFIX.strip().strip("/")
        self._backup_dir = Path(config.BACKUP_DIR)
        self._client = None
        self._bucket = ""
        self._encryption: OffsiteEncryption | None = None
        if self.enabled:
            if not bool(config.BACKUP_OFFSITE_ENCRYPTION_REQUIRED):
                raise BackupExecutionError(
                    "off-site backup configuration",
                    "Client-side encryption is required whenever off-site backup is enabled",
                    status_code=503,
                )
            self._encryption = OffsiteEncryption(
                keyring_file=config.BACKUP_OFFSITE_ENCRYPTION_KEYRING_FILE
            )
            credentials = self._credentials(Path(config.BACKUP_OFFSITE_SECRET_FILE))
            self._bucket = credentials["R2_BACKUP_BUCKET"]
            self._client = boto3.client(
                "s3",
                endpoint_url=credentials["R2_BACKUP_ENDPOINT"],
                aws_access_key_id=credentials["R2_BACKUP_ACCESS_KEY_ID"],
                aws_secret_access_key=credentials["R2_BACKUP_SECRET_ACCESS_KEY"],
                region_name="auto",
                config=Config(
                    signature_version="s3v4",
                    retries={"max_attempts": 4, "mode": "standard"},
                    connect_timeout=10,
                    read_timeout=120,
                ),
            )

    @staticmethod
    def _credentials(path: Path) -> dict[str, str]:
        descriptor: int | None = None
        try:
            descriptor = os.open(
                path,
                os.O_RDONLY
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
            )
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise OSError("credentials are not a single-link regular file")
            if stat.S_IMODE(metadata.st_mode) & 0o077:
                raise OSError("credentials grant group/other permissions")
            if metadata.st_size < 1 or metadata.st_size > 64 * 1024:
                raise OSError("credentials size is invalid")
            payload = bytearray()
            while len(payload) <= metadata.st_size:
                chunk = os.read(
                    descriptor, min(_CHUNK, metadata.st_size + 1 - len(payload))
                )
                if not chunk:
                    break
                payload.extend(chunk)
            if len(payload) != metadata.st_size:
                raise OSError("credentials changed while being read")
            values: dict[str, str] = {}
            for raw in payload.decode("utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                key, separator, value = line.partition("=")
                if not separator or key not in _ALLOWED_KEYS or key in values:
                    raise OSError("credentials contain unsupported fields")
                if not value or "\x00" in value:
                    raise OSError("credentials contain an empty value")
                values[key] = value
            if set(values) != _ALLOWED_KEYS:
                raise OSError("credentials are incomplete")
            endpoint = urlparse(values["R2_BACKUP_ENDPOINT"])
            if (
                endpoint.scheme != "https"
                or not endpoint.hostname
                or not endpoint.hostname.endswith(".r2.cloudflarestorage.com")
                or endpoint.username
                or endpoint.password
                or endpoint.path not in {"", "/"}
                or endpoint.query
                or endpoint.fragment
            ):
                raise OSError("R2 endpoint is not an approved HTTPS endpoint")
            if not _BUCKET.fullmatch(values["R2_BACKUP_BUCKET"]):
                raise OSError("R2 bucket name is invalid")
            return values
        except (OSError, UnicodeError) as exc:
            raise BackupExecutionError(
                "off-site backup configuration",
                "The private R2 backup credential file is unavailable or unsafe",
                status_code=503,
            ) from exc
        finally:
            _close_quietly(descriptor)

    @property
    def client(self):
        if not self.enabled or self._client is None:
            raise BackupExecutionError(
                "off-site backup",
                "Off-site backup replication is not enabled",
                status_code=409,
            )
        return self._client

    @property
    def encryption(self) -> OffsiteEncryption:
        if not self.enabled or self._encryption is None:
            raise BackupExecutionError(
                "off-site backup encryption",
                "Client-side off-site encryption is not available",
                status_code=503,
            )
        return self._encryption

    def preflight(self) -> None:
        if not self.enabled:
            return
        try:
            self.client.head_bucket(Bucket=self._bucket)
        except (BotoCoreError, ClientError) as exc:
            raise BackupExecutionError(
                "off-site backup preflight",
                "The private R2 backup bucket is not reachable with the configured authority",
                status_code=503,
            ) from exc

    def _key(self, backup_id: str, filename: str) -> str:
        if _BACKUP_ID.fullmatch(backup_id) is None:
            raise BackupExecutionError(
                "off-site backup", "Backup identifier is invalid"
            )
        return f"{self._prefix}/{backup_id}/{filename}"

    def _staging_directory(self) -> tempfile.TemporaryDirectory[str]:
        try:
            self._backup_dir.mkdir(parents=True, exist_ok=True)
            staging = tempfile.TemporaryDirectory(
                prefix=".offsite-private-",
                dir=self._backup_dir,
            )
            os.chmod(staging.name, 0o700)
            return staging
        except OSError as exc:
            raise BackupExecutionError(
                "off-site backup staging",
                "Private off-site backup staging could not be created safely",
                status_code=503,
            ) from exc

    def _upload_verified(
        self,
        path: Path,
        key: str,
        checksum: str,
        size: int,
        *,
        metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        expected_metadata = {"sha256": checksum, **(metadata or {})}
        try:
            self.client.upload_file(
                str(path),
                self._bucket,
                key,
                ExtraArgs={
                    "Metadata": expected_metadata,
                    "ContentType": "application/octet-stream",
                },
            )
            head = self.client.head_object(Bucket=self._bucket, Key=key)
            remote_metadata = {
                str(name).lower(): str(value)
                for name, value in (head.get("Metadata") or {}).items()
            }
            if int(head.get("ContentLength", -1)) != size or any(
                remote_metadata.get(name.lower()) != value
                for name, value in expected_metadata.items()
            ):
                raise BackupExecutionError(
                    "off-site backup verification",
                    "R2 object metadata does not match the encrypted backup",
                )
            response = self.client.get_object(Bucket=self._bucket, Key=key)
            digest = hashlib.sha256()
            remote_size = 0
            body = response["Body"]
            try:
                for chunk in iter(lambda: body.read(_CHUNK), b""):
                    digest.update(chunk)
                    remote_size += len(chunk)
            finally:
                body.close()
            if remote_size != size or digest.hexdigest() != checksum:
                raise BackupExecutionError(
                    "off-site backup verification",
                    "R2 full readback checksum does not match the encrypted backup",
                )
            return {"key": key, "sha256": checksum, "size_bytes": size}
        except BackupExecutionError:
            raise
        except (
            BotoCoreError,
            ClientError,
            OSError,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            raise BackupExecutionError(
                "off-site backup replication",
                "The encrypted backup could not be replicated and verified in R2",
                status_code=503,
            ) from exc

    @staticmethod
    def _encryption_evidence(
        encrypted: EncryptedArtifact,
        uploaded: dict[str, Any],
    ) -> dict[str, Any]:
        if (
            uploaded["sha256"] != encrypted.ciphertext_sha256
            or uploaded["size_bytes"] != encrypted.ciphertext_size_bytes
        ):
            raise BackupExecutionError(
                "off-site backup verification",
                "Encrypted upload evidence is inconsistent",
                status_code=409,
            )
        return {
            "key": uploaded["key"],
            "sha256": encrypted.plaintext_sha256,
            "size_bytes": encrypted.plaintext_size_bytes,
            "encryption": {
                "algorithm": encrypted.algorithm,
                "envelope_version": encrypted.envelope_version,
                "key_id": encrypted.key_id,
                "ciphertext_sha256": encrypted.ciphertext_sha256,
                "ciphertext_size_bytes": encrypted.ciphertext_size_bytes,
            },
        }

    def _encrypt_upload(
        self,
        source: Path,
        *,
        staging: Path,
        backup_id: str,
        object_role: str,
        filename: str,
        expected_plaintext_checksum: str,
        expected_plaintext_size: int,
    ) -> dict[str, Any]:
        key = self._key(backup_id, filename)
        encrypted = self.encryption.encrypt_file(
            source,
            staging / filename,
            context=EncryptionContext(
                backup_id=backup_id,
                object_role=object_role,
                r2_object_key=key,
            ),
        )
        if (
            encrypted.plaintext_sha256 != expected_plaintext_checksum
            or encrypted.plaintext_size_bytes != expected_plaintext_size
        ):
            raise BackupExecutionError(
                "off-site backup replication",
                "Backup artifact changed before encrypted R2 upload",
                status_code=409,
            )
        uploaded = self._upload_verified(
            Path(encrypted.location),
            key,
            encrypted.ciphertext_sha256,
            encrypted.ciphertext_size_bytes,
            metadata={
                "aionex-envelope": "aex1",
                "aionex-envelope-version": str(encrypted.envelope_version),
                "aionex-algorithm": encrypted.algorithm,
                "aionex-key-id": encrypted.key_id,
                "aionex-ciphertext-sha256": encrypted.ciphertext_sha256,
            },
        )
        return self._encryption_evidence(encrypted, uploaded)

    def replicate(
        self,
        *,
        backup_id: str,
        database_location: str,
        database_checksum: str,
        database_size: int,
        snapshot: ThreeDAssetSnapshot | None,
    ) -> dict[str, Any]:
        if not self.enabled:
            return {"enabled": False}
        database_path = Path(database_location)
        actual_checksum, actual_size = _sha256(database_path)
        if actual_checksum != database_checksum or actual_size != database_size:
            raise BackupExecutionError(
                "off-site backup replication",
                "The local database artifact changed before encrypted R2 replication",
                status_code=409,
            )
        with self._staging_directory() as staging_name:
            staging = Path(staging_name)
            database = self._encrypt_upload(
                database_path,
                staging=staging,
                backup_id=backup_id,
                object_role="database",
                filename="database.dump.aex1",
                expected_plaintext_checksum=database_checksum,
                expected_plaintext_size=database_size,
            )
            snapshot_evidence = None
            if snapshot is not None:
                snapshot_path = Path(snapshot.location)
                snapshot_checksum, snapshot_size = _sha256(snapshot_path)
                if (
                    snapshot_checksum != snapshot.checksum
                    or snapshot_size != snapshot.size_bytes
                ):
                    raise BackupExecutionError(
                        "off-site backup replication",
                        "The local asset snapshot changed before encrypted R2 replication",
                        status_code=409,
                    )
                snapshot_evidence = self._encrypt_upload(
                    snapshot_path,
                    staging=staging,
                    backup_id=backup_id,
                    object_role="platform_asset_snapshot",
                    filename="platform-assets.tar.aex1",
                    expected_plaintext_checksum=snapshot.checksum,
                    expected_plaintext_size=snapshot.size_bytes,
                )
                snapshot_evidence.update(
                    {
                        "file_count": snapshot.file_count,
                        "payload_bytes": snapshot.payload_bytes,
                    }
                )
                if snapshot.roots:
                    snapshot_evidence["roots"] = snapshot.roots
            manifest_payload = {
                "schema_version": 2,
                "backup_id": backup_id,
                "created_at": datetime.now(UTC).isoformat(),
                "encryption_required": True,
                "database": database,
                "platform_asset_snapshot": snapshot_evidence,
            }
            manifest_bytes = json.dumps(
                manifest_payload,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            manifest_plaintext = staging / "manifest.json"
            _write_private(manifest_plaintext, manifest_bytes)
            manifest = self._encrypt_upload(
                manifest_plaintext,
                staging=staging,
                backup_id=backup_id,
                object_role="manifest",
                filename="manifest.json.aex1",
                expected_plaintext_checksum=hashlib.sha256(manifest_bytes).hexdigest(),
                expected_plaintext_size=len(manifest_bytes),
            )
        evidence = {
            **manifest_payload,
            "enabled": True,
            "manifest": manifest,
            "three_d_snapshot": snapshot_evidence,
        }
        self.prune()
        return evidence

    def prune(self) -> None:
        """Keep the newest configured number of complete encrypted or legacy prefixes."""
        keep = self._settings.BACKUP_OFFSITE_RETENTION_COUNT
        try:
            paginator = self.client.get_paginator("list_objects_v2")
            complete: dict[str, tuple[Any, str]] = {}
            prefix = f"{self._prefix}/"
            for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
                for item in page.get("Contents", []):
                    key = str(item.get("Key", ""))
                    if not (
                        key.endswith("/manifest.json.aex1")
                        or key.endswith("/manifest.json")
                    ):
                        continue
                    backup_prefix = key.rsplit("/", 1)[0] + "/"
                    modified = item.get("LastModified")
                    previous = complete.get(backup_prefix)
                    if previous is None or modified > previous[0]:
                        complete[backup_prefix] = (modified, key)
            manifests = sorted(
                complete.values(), key=lambda item: item[0], reverse=True
            )
            for _modified, manifest_key in manifests[keep:]:
                backup_prefix = manifest_key.rsplit("/", 1)[0] + "/"
                objects: list[dict[str, str]] = []
                for page in paginator.paginate(
                    Bucket=self._bucket,
                    Prefix=backup_prefix,
                ):
                    objects.extend(
                        {"Key": str(item["Key"])} for item in page.get("Contents", [])
                    )
                if objects:
                    self.client.delete_objects(
                        Bucket=self._bucket,
                        Delete={"Objects": objects, "Quiet": True},
                    )
        except (BotoCoreError, ClientError, KeyError, TypeError, ValueError) as exc:
            raise BackupExecutionError(
                "off-site backup retention",
                "R2 retention cleanup failed",
                status_code=503,
            ) from exc

    @staticmethod
    def _encrypted_fields(item: Any) -> tuple[str, int, str, int, str]:
        if not isinstance(item, dict):
            raise ValueError("artifact evidence is not an object")
        required = {"key", "sha256", "size_bytes", "encryption"}
        allowed = required | {"file_count", "payload_bytes", "roots"}
        if not required.issubset(item) or not set(item).issubset(allowed):
            raise ValueError("artifact evidence schema is invalid")
        key = item["key"]
        if not isinstance(key, str) or not key or "\x00" in key:
            raise ValueError("artifact key is invalid")
        plaintext_checksum = _valid_checksum(item["sha256"])
        plaintext_size = _valid_size(item["size_bytes"])
        encryption = item["encryption"]
        if not isinstance(encryption, dict) or set(encryption) != _ENCRYPTION_FIELDS:
            raise ValueError("encryption evidence schema is invalid")
        if (
            encryption["algorithm"] != "AES-256-GCM"
            or encryption["envelope_version"] != 1
        ):
            raise ValueError("encryption evidence version is invalid")
        key_id = encryption["key_id"]
        if not isinstance(key_id, str) or not key_id:
            raise ValueError("encryption key identifier is invalid")
        ciphertext_checksum = _valid_checksum(encryption["ciphertext_sha256"])
        ciphertext_size = _valid_size(encryption["ciphertext_size_bytes"])
        return (
            plaintext_checksum,
            plaintext_size,
            ciphertext_checksum,
            ciphertext_size,
            key_id,
        )

    def _download_encrypted(
        self,
        item: Any,
        *,
        staging: Path,
        destination: Path,
        backup_id: str,
        object_role: str,
        expected_filename: str,
    ) -> None:
        (
            plaintext_checksum,
            plaintext_size,
            ciphertext_checksum,
            ciphertext_size,
            key_id,
        ) = self._encrypted_fields(item)
        expected_key = self._key(backup_id, expected_filename)
        if item["key"] != expected_key:
            raise BackupExecutionError(
                "off-site restore validation",
                "Encrypted R2 artifact key does not match its authenticated context",
                status_code=409,
            )
        encrypted_path = staging / expected_filename
        self.client.download_file(self._bucket, expected_key, str(encrypted_path))
        os.chmod(encrypted_path, 0o600)
        actual_ciphertext_checksum, actual_ciphertext_size = _sha256(encrypted_path)
        if (
            actual_ciphertext_checksum != ciphertext_checksum
            or actual_ciphertext_size != ciphertext_size
        ):
            raise BackupExecutionError(
                "off-site restore validation",
                "Downloaded encrypted R2 artifact failed ciphertext validation",
                status_code=409,
            )
        (
            restored_checksum,
            restored_size,
            restored_key_id,
        ) = self.encryption.decrypt_file(
            encrypted_path,
            destination,
            context=EncryptionContext(
                backup_id=backup_id,
                object_role=object_role,
                r2_object_key=expected_key,
            ),
        )
        if (
            restored_checksum != plaintext_checksum
            or restored_size != plaintext_size
            or restored_key_id != key_id
        ):
            raise BackupExecutionError(
                "off-site restore validation",
                "Decrypted R2 artifact does not match durable encryption evidence",
                status_code=409,
            )

    @staticmethod
    def _publish_legacy(
        source: Path,
        destination: Path,
        *,
        checksum: str,
        size: int,
    ) -> None:
        actual_checksum, actual_size = _sha256(source)
        if actual_checksum != checksum or actual_size != size:
            raise BackupExecutionError(
                "off-site restore validation",
                "Downloaded legacy R2 artifact failed checksum validation",
                status_code=409,
            )
        try:
            os.link(source, destination, follow_symlinks=False)
            source.unlink()
        except FileExistsError as exc:
            raise BackupExecutionError(
                "off-site restore validation",
                "Restore-validation destination already exists",
                status_code=409,
            ) from exc
        except OSError as exc:
            raise BackupExecutionError(
                "off-site restore validation",
                "Legacy restore-validation artifact could not be published safely",
                status_code=503,
            ) from exc

    def _download_legacy(
        self,
        item: Any,
        *,
        staging: Path,
        destination: Path,
        backup_id: str,
        expected_filename: str,
    ) -> None:
        if not isinstance(item, dict) or set(item) - {
            "key",
            "sha256",
            "size_bytes",
            "file_count",
            "payload_bytes",
            "roots",
        }:
            raise ValueError("legacy artifact evidence schema is invalid")
        expected_key = self._key(backup_id, expected_filename)
        if item.get("key") != expected_key:
            raise ValueError("legacy artifact key is invalid")
        checksum = _valid_checksum(item.get("sha256"))
        size = _valid_size(item.get("size_bytes"))
        staged = staging / expected_filename
        self.client.download_file(self._bucket, expected_key, str(staged))
        os.chmod(staged, 0o600)
        self._publish_legacy(staged, destination, checksum=checksum, size=size)

    def download_for_validation(
        self,
        evidence: dict[str, Any],
        *,
        validation_id: str,
        attempt_token: str,
    ) -> OffsiteValidationArtifacts:
        if not self.enabled:
            raise BackupExecutionError(
                "off-site restore validation",
                "Off-site backup is not enabled",
                status_code=409,
            )
        database = evidence.get("database")
        snapshot = evidence.get("three_d_snapshot")
        backup_id = evidence.get("backup_id")
        schema_version = evidence.get("schema_version")
        if not isinstance(backup_id, str) or _BACKUP_ID.fullmatch(backup_id) is None:
            raise BackupExecutionError(
                "off-site restore validation",
                "Off-site backup evidence has an invalid backup identifier",
                status_code=409,
            )
        stable = hashlib.sha256(validation_id.encode()).hexdigest()[:24]
        attempt = hashlib.sha256(attempt_token.encode()).hexdigest()[:32]
        database_path = self._backup_dir / f"backup-{stable}-{attempt}.dump"
        snapshot_path = (
            self._backup_dir / f"backup-{stable}-{attempt}.three-d.tar"
        )
        try:
            with self._staging_directory() as staging_name:
                staging = Path(staging_name)
                if schema_version == 2 and evidence.get("encryption_required") is True:
                    self._download_encrypted(
                        database,
                        staging=staging,
                        destination=database_path,
                        backup_id=backup_id,
                        object_role="database",
                        expected_filename="database.dump.aex1",
                    )
                    if snapshot is not None:
                        self._download_encrypted(
                            snapshot,
                            staging=staging,
                            destination=snapshot_path,
                            backup_id=backup_id,
                            object_role="platform_asset_snapshot",
                            expected_filename="platform-assets.tar.aex1",
                        )
                elif schema_version == 1:
                    self._download_legacy(
                        database,
                        staging=staging,
                        destination=database_path,
                        backup_id=backup_id,
                        expected_filename="database.dump",
                    )
                    if snapshot is not None:
                        self._download_legacy(
                            snapshot,
                            staging=staging,
                            destination=snapshot_path,
                            backup_id=backup_id,
                            expected_filename="three-d.tar",
                        )
                else:
                    raise BackupExecutionError(
                        "off-site restore validation",
                        "Off-site backup evidence is not an approved encrypted or legacy schema",
                        status_code=409,
                    )
            return OffsiteValidationArtifacts(
                str(database_path),
                str(snapshot_path) if snapshot is not None else None,
            )
        except BackupExecutionError:
            self.cleanup_validation(database_path, snapshot_path)
            raise
        except (
            BotoCoreError,
            ClientError,
            OSError,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            self.cleanup_validation(database_path, snapshot_path)
            raise BackupExecutionError(
                "off-site restore validation",
                "R2 restore-validation artifacts could not be downloaded safely",
                status_code=503,
            ) from exc

    @staticmethod
    def cleanup_validation(
        database_path: Path | str,
        snapshot_path: Path | str | None,
    ) -> None:
        first_error: OSError | None = None
        for path in (database_path, snapshot_path):
            if path:
                try:
                    Path(path).unlink(missing_ok=True)
                except OSError as exc:
                    if first_error is None:
                        first_error = exc
        if first_error is not None:
            raise BackupCleanupIncomplete(
                "Off-site validation cleanup",
                "The downloaded restore-validation artifacts could not all be removed",
            ) from first_error
