"""Phase 36D local/S3-compatible private media object storage abstraction."""
from __future__ import annotations

import os
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

import boto3  # type: ignore[import-untyped]
from botocore.config import Config  # type: ignore[import-untyped]
from botocore.exceptions import BotoCoreError, ClientError  # type: ignore[import-untyped]

from app.core.config import settings


class MediaStorageError(RuntimeError):
    """Sanitized media-storage failure."""


@dataclass(frozen=True, slots=True)
class StoredMediaObject:
    key: str
    size_bytes: int
    sha256: str
    content_type: str
    backend: str


class MediaObjectStore(Protocol):
    def put_bytes(
        self, key: str, body: bytes, content_type: str, *, metadata: dict[str, str] | None = None
    ) -> StoredMediaObject: ...

    def get_bytes(self, key: str, *, max_bytes: int) -> bytes: ...

    def delete(self, key: str) -> None: ...

    def presigned_get(
        self,
        key: str,
        *,
        filename: str,
        content_type: str,
        expires_seconds: int,
        inline: bool,
    ) -> str | None: ...


class LocalMediaObjectStore:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root or settings.MEDIA_STORAGE_ROOT).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.chmod(self.root, 0o700)
        except OSError:
            pass

    def _path(self, key: str) -> Path:
        normalized = key.strip().lstrip("/")
        if not normalized or ".." in Path(normalized).parts:
            raise MediaStorageError("media object key is invalid")
        candidate = (self.root / normalized).resolve()
        if self.root not in candidate.parents:
            raise MediaStorageError("media object key escapes the private root")
        return candidate

    def put_bytes(
        self, key: str, body: bytes, content_type: str, *, metadata: dict[str, str] | None = None
    ) -> StoredMediaObject:
        del metadata
        if len(body) > settings.MEDIA_MAX_OBJECT_BYTES:
            raise MediaStorageError("media object exceeds the configured size limit")
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = path.with_name(f".{path.name}.partial")
        temporary.write_bytes(body)
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        return StoredMediaObject(
            key=key,
            size_bytes=len(body),
            sha256=sha256(body).hexdigest(),
            content_type=content_type,
            backend="local",
        )

    def get_bytes(self, key: str, *, max_bytes: int) -> bytes:
        limit = min(max(1, int(max_bytes)), settings.MEDIA_MAX_OBJECT_BYTES)
        path = self._path(key)
        try:
            size = path.stat().st_size
            if size <= 0 or size > limit:
                raise MediaStorageError("media object size is outside the allowed range")
            body = path.read_bytes()
        except FileNotFoundError as exc:
            raise MediaStorageError("media object is unavailable") from exc
        if len(body) != size:
            raise MediaStorageError("media object changed during read")
        return body

    def delete(self, key: str) -> None:
        try:
            self._path(key).unlink(missing_ok=True)
        except OSError:
            return

    def presigned_get(
        self,
        key: str,
        *,
        filename: str,
        content_type: str,
        expires_seconds: int,
        inline: bool,
    ) -> None:
        del key, filename, content_type, expires_seconds, inline
        return None


class S3CompatibleMediaObjectStore:
    def __init__(self) -> None:
        bucket = str(settings.MEDIA_S3_BUCKET or settings.AWS_S3_BUCKET or "").strip()
        region = str(settings.MEDIA_S3_REGION or settings.AWS_S3_REGION or "").strip()
        access_key = str(settings.MEDIA_S3_ACCESS_KEY_ID or settings.AWS_ACCESS_KEY_ID or "").strip()
        secret_key = str(
            settings.MEDIA_S3_SECRET_ACCESS_KEY or settings.AWS_SECRET_ACCESS_KEY or ""
        ).strip()
        if not bucket or not region or not access_key or not secret_key:
            raise MediaStorageError("S3-compatible media storage is not configured")
        self.bucket = bucket
        self.region = region
        self.endpoint_url = (settings.MEDIA_S3_ENDPOINT_URL or "").strip() or None
        self.client = boto3.client(
            "s3",
            endpoint_url=self.endpoint_url,
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(
                signature_version="s3v4",
                retries={"max_attempts": 4, "mode": "standard"},
            ),
        )

    def put_bytes(
        self, key: str, body: bytes, content_type: str, *, metadata: dict[str, str] | None = None
    ) -> StoredMediaObject:
        if len(body) > settings.MEDIA_MAX_OBJECT_BYTES:
            raise MediaStorageError("media object exceeds the configured size limit")
        digest = sha256(body).hexdigest()
        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=body,
                ContentType=content_type,
                Metadata={"sha256": digest, **(metadata or {})},
            )
        except (BotoCoreError, ClientError, OSError) as exc:
            raise MediaStorageError(
                f"media object upload failed: {type(exc).__name__}"
            ) from None
        return StoredMediaObject(
            key=key,
            size_bytes=len(body),
            sha256=digest,
            content_type=content_type,
            backend="s3",
        )

    def get_bytes(self, key: str, *, max_bytes: int) -> bytes:
        limit = min(max(1, int(max_bytes)), settings.MEDIA_MAX_OBJECT_BYTES)
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
            declared = int(response.get("ContentLength") or 0)
            if declared <= 0 or declared > limit:
                raise MediaStorageError("media object size is outside the allowed range")
            body = response["Body"].read(limit + 1)
        except MediaStorageError:
            raise
        except (BotoCoreError, ClientError, OSError, KeyError) as exc:
            raise MediaStorageError(
                f"media object download failed: {type(exc).__name__}"
            ) from None
        if len(body) > limit:
            raise MediaStorageError("media object exceeds the allowed size")
        return body

    def delete(self, key: str) -> None:
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
        except (BotoCoreError, ClientError, OSError):
            return

    def presigned_get(
        self,
        key: str,
        *,
        filename: str,
        content_type: str,
        expires_seconds: int,
        inline: bool,
    ) -> str:
        ttl = max(60, min(int(expires_seconds), 3600))
        disposition = "inline" if inline else "attachment"
        safe_name = quote(filename, safe="._-")
        try:
            return str(
                self.client.generate_presigned_url(
                    "get_object",
                    Params={
                        "Bucket": self.bucket,
                        "Key": key,
                        "ResponseContentType": content_type,
                        "ResponseContentDisposition": (
                            f"{disposition}; filename*=UTF-8''{safe_name}"
                        ),
                    },
                    ExpiresIn=ttl,
                )
            )
        except (BotoCoreError, ClientError, OSError):
            raise MediaStorageError("media signed URL creation failed") from None


def media_object_store() -> MediaObjectStore:
    storage_type = settings.MEDIA_STORAGE_TYPE.strip().lower()
    if storage_type == "local":
        return LocalMediaObjectStore()
    if storage_type in {"s3", "r2", "s3-compatible"}:
        return S3CompatibleMediaObjectStore()
    raise MediaStorageError("unsupported media storage backend")
