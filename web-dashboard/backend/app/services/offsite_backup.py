"""Cloudflare R2 off-site backup replication and readback validation.

Credentials are loaded only from a private mounted file. Backup objects remain in a
private bucket and are verified by full SHA-256 readback after upload. Cloudflare R2
provides TLS in transit and automatic AES-256 encryption at rest.
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
from typing import Any
from urllib.parse import urlparse

import boto3  # type: ignore[import-untyped]
from botocore.config import Config  # type: ignore[import-untyped]
from botocore.exceptions import BotoCoreError, ClientError  # type: ignore[import-untyped]

from app.core.config import Settings, settings
from app.services.backup_executor import BackupExecutionError
from app.services.three_d_asset_backup import ThreeDAssetSnapshot

_CHUNK = 1024 * 1024
_BUCKET = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
_ALLOWED_KEYS = {
    "R2_BACKUP_ENDPOINT",
    "R2_BACKUP_BUCKET",
    "R2_BACKUP_ACCESS_KEY_ID",
    "R2_BACKUP_SECRET_ACCESS_KEY",
}


@dataclass(frozen=True, slots=True)
class OffsiteValidationArtifacts:
    database_location: str
    snapshot_location: str | None


def _sha256(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise OSError("artifact is not a regular file")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            for chunk in iter(lambda: stream.read(_CHUNK), b""):
                digest.update(chunk)
                size += len(chunk)
    finally:
        os.close(descriptor)
    return digest.hexdigest(), size


class OffsiteBackupReplicator:
    def __init__(self, config: Settings = settings) -> None:
        self._settings = config
        self.enabled = bool(config.BACKUP_OFFSITE_ENABLED)
        self._prefix = config.BACKUP_OFFSITE_PREFIX.strip().strip("/")
        self._backup_dir = Path(config.BACKUP_DIR)
        self._client = None
        self._bucket = ""
        if self.enabled:
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
        try:
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                raise OSError("credentials are not a regular file")
            if stat.S_IMODE(metadata.st_mode) & 0o077:
                raise OSError("credentials grant group/other permissions")
            values: dict[str, str] = {}
            for raw in path.read_text(encoding="utf-8").splitlines():
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
        except OSError as exc:
            raise BackupExecutionError(
                "off-site backup configuration",
                "The private R2 backup credential file is unavailable or unsafe",
                status_code=503,
            ) from exc

    @property
    def client(self):
        if not self.enabled or self._client is None:
            raise BackupExecutionError(
                "off-site backup",
                "Off-site backup replication is not enabled",
                status_code=409,
            )
        return self._client

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
        if not re.fullmatch(r"[0-9a-fA-F-]{36}", backup_id):
            raise BackupExecutionError("off-site backup", "Backup identifier is invalid")
        return f"{self._prefix}/{backup_id}/{filename}"

    def _upload_verified(self, path: Path, key: str, checksum: str, size: int) -> dict[str, Any]:
        try:
            self.client.upload_file(
                str(path), self._bucket, key,
                ExtraArgs={"Metadata": {"sha256": checksum}, "ContentType": "application/octet-stream"},
            )
            head = self.client.head_object(Bucket=self._bucket, Key=key)
            if int(head.get("ContentLength", -1)) != size or str((head.get("Metadata") or {}).get("sha256", "")) != checksum:
                raise BackupExecutionError("off-site backup verification", "R2 object metadata does not match the local backup")
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
                raise BackupExecutionError("off-site backup verification", "R2 full readback checksum does not match the local backup")
            return {"key": key, "sha256": checksum, "size_bytes": size}
        except BackupExecutionError:
            raise
        except (BotoCoreError, ClientError, OSError) as exc:
            raise BackupExecutionError("off-site backup replication", "The backup could not be replicated and verified in R2", status_code=503) from exc

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
            raise BackupExecutionError("off-site backup replication", "The local database artifact changed before R2 replication", status_code=409)
        database = self._upload_verified(database_path, self._key(backup_id, "database.dump"), database_checksum, database_size)
        snapshot_evidence = None
        if snapshot is not None:
            snapshot_path = Path(snapshot.location)
            snapshot_checksum, snapshot_size = _sha256(snapshot_path)
            if snapshot_checksum != snapshot.checksum or snapshot_size != snapshot.size_bytes:
                raise BackupExecutionError("off-site backup replication", "The local asset snapshot changed before R2 replication", status_code=409)
            snapshot_evidence = self._upload_verified(snapshot_path, self._key(backup_id, "three-d.tar"), snapshot.checksum, snapshot.size_bytes)
            snapshot_evidence.update({"file_count": snapshot.file_count, "payload_bytes": snapshot.payload_bytes})
            if snapshot.roots:
                snapshot_evidence["roots"] = snapshot.roots
        manifest = {
            "schema_version": 1,
            "backup_id": backup_id,
            "created_at": datetime.now(UTC).isoformat(),
            "database": database,
            "three_d_snapshot": snapshot_evidence,
        }
        payload = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
        manifest_checksum = hashlib.sha256(payload).hexdigest()
        manifest_key = self._key(backup_id, "manifest.json")
        try:
            self.client.put_object(Bucket=self._bucket, Key=manifest_key, Body=payload, ContentType="application/json", Metadata={"sha256": manifest_checksum})
            remote = self.client.get_object(Bucket=self._bucket, Key=manifest_key)["Body"].read()
            if hashlib.sha256(remote).hexdigest() != manifest_checksum or remote != payload:
                raise BackupExecutionError("off-site backup verification", "R2 manifest readback failed integrity validation")
        except BackupExecutionError:
            raise
        except (BotoCoreError, ClientError) as exc:
            raise BackupExecutionError("off-site backup replication", "The R2 backup manifest could not be committed", status_code=503) from exc
        manifest["manifest"] = {"key": manifest_key, "sha256": manifest_checksum, "size_bytes": len(payload)}
        self.prune()
        return manifest

    def prune(self) -> None:
        """Keep the newest configured number of complete backup prefixes."""
        keep = self._settings.BACKUP_OFFSITE_RETENTION_COUNT
        try:
            paginator = self.client.get_paginator("list_objects_v2")
            manifests: list[tuple[Any, str]] = []
            prefix = f"{self._prefix}/"
            for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
                for item in page.get("Contents", []):
                    key = str(item.get("Key", ""))
                    if key.endswith("/manifest.json"):
                        manifests.append((item.get("LastModified"), key))
            manifests.sort(key=lambda item: item[0], reverse=True)
            for _modified, manifest_key in manifests[keep:]:
                backup_prefix = manifest_key[: -len("manifest.json")]
                objects: list[dict[str, str]] = []
                for page in paginator.paginate(Bucket=self._bucket, Prefix=backup_prefix):
                    objects.extend({"Key": str(item["Key"])} for item in page.get("Contents", []))
                if objects:
                    self.client.delete_objects(Bucket=self._bucket, Delete={"Objects": objects, "Quiet": True})
        except (BotoCoreError, ClientError) as exc:
            raise BackupExecutionError("off-site backup retention", "R2 retention cleanup failed", status_code=503) from exc

    def download_for_validation(self, evidence: dict[str, Any], *, validation_id: str, attempt_token: str) -> OffsiteValidationArtifacts:
        if not self.enabled:
            raise BackupExecutionError("off-site restore validation", "Off-site backup is not enabled", status_code=409)
        database = evidence.get("database") or {}
        snapshot = evidence.get("three_d_snapshot")
        stable = hashlib.sha256(validation_id.encode()).hexdigest()[:24]
        attempt = hashlib.sha256(attempt_token.encode()).hexdigest()[:32]
        database_path = self._backup_dir / f"backup-{stable}-{attempt}.dump"
        snapshot_path = self._backup_dir / f"backup-{stable}-{attempt}.three-d.tar"
        try:
            self.client.download_file(self._bucket, str(database["key"]), str(database_path))
            os.chmod(database_path, 0o600)
            checksum, size = _sha256(database_path)
            if checksum != str(database["sha256"]) or size != int(database["size_bytes"]):
                raise BackupExecutionError("off-site restore validation", "Downloaded R2 database backup failed checksum validation", status_code=409)
            if snapshot:
                self.client.download_file(self._bucket, str(snapshot["key"]), str(snapshot_path))
                os.chmod(snapshot_path, 0o600)
                checksum, size = _sha256(snapshot_path)
                if checksum != str(snapshot["sha256"]) or size != int(snapshot["size_bytes"]):
                    raise BackupExecutionError("off-site restore validation", "Downloaded R2 asset snapshot failed checksum validation", status_code=409)
            return OffsiteValidationArtifacts(str(database_path), str(snapshot_path) if snapshot else None)
        except BackupExecutionError:
            self.cleanup_validation(database_path, snapshot_path)
            raise
        except (BotoCoreError, ClientError, OSError, KeyError, TypeError, ValueError) as exc:
            self.cleanup_validation(database_path, snapshot_path)
            raise BackupExecutionError("off-site restore validation", "R2 restore-validation artifacts could not be downloaded safely", status_code=503) from exc

    @staticmethod
    def cleanup_validation(database_path: Path | str, snapshot_path: Path | str | None) -> None:
        for path in (database_path, snapshot_path):
            if path:
                try:
                    Path(path).unlink(missing_ok=True)
                except OSError:
                    continue
